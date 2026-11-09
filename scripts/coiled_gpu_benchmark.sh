#!/usr/bin/env bash
# Benchmark the pipeline on several Coiled GPU instance types, one after another.
#
# Each instance type runs 4 live inits (one per 5-min GOES scan) and publishes them to
# the Arraylake booth repo, then the VM stops: no --detach and no --keepalive, so Coiled
# shuts the VM down when the command exits. `timeout` in the VM is a hard cap in case the
# pipeline hangs. Results: logs/bench/<instance>.log and a summary table at the end
# (mean of the last 3 inits; the first pays the torch.compile warmup).
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

for vm in "${VM_TYPES[@]}"; do
    log="logs/bench/${vm}.log"
    for try in $(seq 1 $TRIES); do
        echo "$(date -u +%H:%M:%SZ) ${vm}: launch try ${try}" | tee -a logs/bench/progress.log
        uv run coiled run --workspace earthmover-devs --name "stormscope-us-bench-${vm//./-}" \
            --region us-east-1 --ami-version DL --vm-type "$vm" \
            --container nvcr.io/nvidia/physicsnemo/physicsnemo:26.08 --root --disk-size 200 \
            --docker-shm-size "1 GiB" --file scripts/ \
            --env ARRAYLAKE_API_TOKEN="$ARRAYLAKE_API_TOKEN" \
            -- timeout "$HARD_CAP" bash scripts/coiled_bootstrap.sh --n-steps 12 \
               --max-runs "$RUNS" --publish-target arraylake \
               --arraylake-repo nvidia/sc26-chicago-stormscope_us-booth \
            > "$log" 2>&1
        grep -q "InsufficientInstanceCapacity" "$log" || break
        echo "$(date -u +%H:%M:%SZ) ${vm}: no capacity, retry in 2 min" | tee -a logs/bench/progress.log
        sleep 120
    done
    echo "$(date -u +%H:%M:%SZ) ${vm}: finished" | tee -a logs/bench/progress.log
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
