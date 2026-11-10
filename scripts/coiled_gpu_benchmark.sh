#!/usr/bin/env bash
# Benchmark the pipeline on several Coiled GPU instance types, one after another.
#
# Each instance type runs 4 live inits (one per 5-min GOES scan) and publishes them to
# the Arraylake booth repo, then the VM stops. The run uses --detach with --keepalive 30m:
# without a keepalive, Coiled stopped the VM during the first pip install (clusters 2352426,
# 2355602); with one, runs worked. So this script stops each cluster itself as soon as the
# VM log shows `--max-runs ... reached` or a bootstrap `done`/`FAILED`. --skip-ssd-mount: on g6e.4xlarge
# with the DL AMI, formatting the local NVMe failed ("Device or resource busy"), /scratch
# was missing and Coiled stopped the cluster (2026-11-10). `timeout` in the VM caps the
# pipeline, and this script stops the cluster itself if it is still up after MAX_WAIT.
# Results: logs/bench/<instance>.log (VM logs) and a summary table at the end (mean of
# the last 3 inits; the first pays the torch.compile warmup).
#
#   bash scripts/coiled_gpu_benchmark.sh                      # default list below
#   bash scripts/coiled_gpu_benchmark.sh g6.xlarge g5.xlarge  # only these
#
# Needs ARRAYLAKE_API_TOKEN in .env. See docs/GPU.md, "Inference timing log".
set -uo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
: "${ARRAYLAKE_API_TOKEN:?ARRAYLAKE_API_TOKEN missing in .env}"

VM_TYPES=("$@")
[ ${#VM_TYPES[@]} -eq 0 ] && VM_TYPES=(g6e.4xlarge g6e.xlarge g6.xlarge g5.xlarge)
RUNS=4           # live inits per instance type
HARD_CAP=45m     # kill the pipeline after this, whatever happens
TRIES=10         # launch attempts per instance type while AWS has no capacity
mkdir -p logs/bench

MAX_WAIT=$((50 * 60))  # seconds; local backstop after HARD_CAP

state() {  # Coiled state of cluster id $1 (ready, stopped, error, ...)
    uv run python -c "
import coiled, sys
with coiled.Cloud(workspace='earthmover-devs') as c:
    print(c.cluster_details(int(sys.argv[1]), workspace='earthmover-devs')['current_state']['state'])
" "$1" 2>/dev/null | tail -1
}

for vm in "${VM_TYPES[@]}"; do
    log="logs/bench/${vm}.log"
    launch="logs/bench/${vm}.launch.log"
    id=""
    for try in $(seq 1 $TRIES); do
        echo "$(date -u +%H:%M:%SZ) ${vm}: launch try ${try}" | tee -a logs/bench/progress.log
        uv run coiled run --workspace earthmover-devs --name "stormscope-us-bench-${vm//./-}" \
            --region us-east-1 --ami-version DL --vm-type "$vm" \
            --container nvcr.io/nvidia/physicsnemo/physicsnemo:26.08 --root --disk-size 200 \
            --docker-shm-size "1 GiB" --file scripts/ --detach --skip-ssd-mount --keepalive 30m \
            --env ARRAYLAKE_API_TOKEN="$ARRAYLAKE_API_TOKEN" \
            -- timeout "$HARD_CAP" bash scripts/coiled_bootstrap.sh --n-steps 12 \
               --max-runs "$RUNS" --publish-target arraylake \
               --arraylake-repo nvidia/sc26-chicago-stormscope_us-booth \
            > "$launch" 2>&1
        id=$(sed 's/\x1b\[[0-9;]*m//g' "$launch" | grep -oE "clusters/[0-9]+" | head -1 | cut -d/ -f2)
        if sed 's/\x1b\[[0-9;]*m//g' "$launch" | grep -qE "VM Type: +[a-z]"; then break; fi
        if grep -q "InsufficientInstanceCapacity" "$launch"; then
            echo "$(date -u +%H:%M:%SZ) ${vm}: no capacity, retry in 2 min" | tee -a logs/bench/progress.log
            id=""; sleep 120; continue
        fi
        echo "$(date -u +%H:%M:%SZ) ${vm}: launch failed (cluster ${id:-none}), see ${launch}" | tee -a logs/bench/progress.log
        id=""; break
    done
    if [ -n "$id" ]; then
        echo "$(date -u +%H:%M:%SZ) ${vm}: running as cluster ${id}" | tee -a logs/bench/progress.log
        start=$(date +%s)
        while true; do
            sleep 60
            st=$(state "$id")
            case "$st" in stopped|error) break;; esac
            if uv run coiled logs --workspace earthmover-devs --cluster "$id" --label none 2>/dev/null \
                | sed 's/\x1b\[[0-9;]*m//g' | grep -qE "max-runs [0-9]+ reached|\[bootstrap\] .*(done|FAILED)"; then
                echo "$(date -u +%H:%M:%SZ) ${vm}: run finished, stopping cluster ${id}" | tee -a logs/bench/progress.log
                sleep 20  # let the last log lines ship
                uv run coiled cluster stop --workspace earthmover-devs "$id" >/dev/null 2>&1
                break
            fi
            if [ $(( $(date +%s) - start )) -gt $MAX_WAIT ]; then
                echo "$(date -u +%H:%M:%SZ) ${vm}: still ${st} after ${MAX_WAIT}s, stopping it" | tee -a logs/bench/progress.log
                uv run coiled cluster stop --workspace earthmover-devs "$id" >/dev/null 2>&1
                break
            fi
        done
        uv run coiled logs --workspace earthmover-devs --cluster "$id" --label none > "$log" 2>&1
    fi
    echo "$(date -u +%H:%M:%SZ) ${vm}: finished (cluster ${id:-none})" | tee -a logs/bench/progress.log
done

# Summary: mean of the last 3 `timing:` lines per instance type, with the us-east-1
# on-demand price (instances.vantage.sh, 2026-11-09; see docs/GPU.md).
price() { case "$1" in
    g6e.8xlarge) echo 4.53;; g6e.4xlarge) echo 1.98;; g6e.2xlarge) echo 2.24;; g6e.xlarge) echo 1.86;;
    g6.xlarge) echo 0.80;; g5.xlarge) echo 1.01;; g7e.2xlarge) echo 3.36;; g7e.8xlarge) echo 5.27;;
    p5.4xlarge) echo 6.88;; *) echo "?";; esac; }
echo
printf "%-13s %6s %5s %8s %10s %8s %8s\n" instance usd_h inits fetch_s rollout_s commit_s total_s
for vm in "${VM_TYPES[@]}"; do
    sed 's/\x1b\[[0-9;]*m//g' "logs/bench/${vm}.log" 2>/dev/null | grep -o "timing: .*" \
        | tail -3 | awk -v vm="$vm" -v usd="$(price "$vm")" '
        { gsub(/[s,]/, ""); f += $3; r += $5; c += $7; t += $9; n++ }
        END { if (n) printf "%-13s %6s %5d %8.1f %10.1f %8.1f %8.1f\n", vm, usd, n, f/n, r/n, c/n, t/n
              else printf "%-13s %6s %5d   (no completed runs, see logs/bench/%s.log)\n", vm, usd, 0, vm }'
done | tee -a logs/bench/progress.log
