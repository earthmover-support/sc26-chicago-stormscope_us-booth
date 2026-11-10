# GPU options in AWS us-east-1

The pipeline runs in AWS **us-east-1**. This is the same region as the NOAA GOES-19
bucket (`noaa-goes19`), so there is no cross-region transfer (see `AGENTS.md`).
GPU VMs are started with [Coiled](https://docs.coiled.io) (dev dependency) in the
`earthmover-devs` workspace (AWS backend, default region us-west-2, so every command
passes `--region us-east-1`).

At GTC Berlin we used a B200 (`p6-b200.48xlarge`).

## Instance types

Status on 2026-11-09. Coiled lists these GPU instance types
(`coiled.list_instance_types(backend="aws")`). Prices are us-east-1 on-demand
prices from instances.vantage.sh. They are not checked against the AWS Pricing API.

| Instance | GPUs | vCPU / RAM | On-demand $/h | $/GPU/h |
|---|---|---|---|---|
| `p6-b300.48xlarge` | 8x B300 | 192 / 4 TiB | 142.42 | 17.80 |
| `p6-b200.48xlarge` | 8x B200 | 192 / 2 TiB | 113.93 | 14.24 |
| `p5en.48xlarge` | 8x H200 | 192 / 2 TiB | 63.30 | 7.91 |
| `p5.48xlarge` | 8x H100 | 192 / 2 TiB | 55.04 | 6.88 |
| `p5.4xlarge` | 1x H100 | 16 / 256 GiB | 6.88 | 6.88 |
| `g7e.8xlarge` | 1x RTX PRO 6000 Server | 32 / 256 GiB | 5.27 | 5.27 |
| `g7e.2xlarge` | 1x RTX PRO 6000 Server | 8 / 64 GiB | 3.36 | 3.36 |
| `g6e.xlarge` | 1x L40S | 4 / 32 GiB | 1.86 | 1.86 |

Coiled also lists multi-GPU sizes of `g6e` (4x/8x L40S) and `g7e` (2x/4x/8x RTX PRO
6000 Server).

## Notes

- **B200, B300 and H200 come only as 8-GPU nodes.** A pipeline that uses one GPU
  pays for eight. A single-GPU option costs about 16x less per hour than a B200
  node. The speed difference for StormScope is not measured yet.
- **Capacity:** B200, B300 and H200 usually need a raised EC2 GPU quota or an
  [EC2 Capacity Block](https://aws.amazon.com/ec2/capacityblocks/). On-demand
  capacity in us-east-1 is often not available. Book before the booth days.
- **Single-GPU candidates**, from fastest to cheapest: `p5.4xlarge` (H100),
  `g7e.*` (RTX PRO 6000 Server, Blackwell, 96 GB), `g6e.*` (L40S, 48 GB).

## Single-GPU types below $10/h

The pipeline uses one GPU. From fastest to slowest (us-east-1 on-demand $/h):

| GPU | Instances ($/h) |
|---|---|
| H100 80 GB | `p5.4xlarge` (6.88) |
| RTX PRO 6000 Server 96 GB (Blackwell) | `g7e.2xlarge` (3.36), `g7e.4xlarge` (4.00), `g7e.8xlarge` (5.27) |
| L40S 48 GB | `g6e.xlarge` (1.86), `g6e.2xlarge` (2.24), `g6e.4xlarge` (1.98), `g6e.8xlarge` (4.53), `g6e.16xlarge` (7.58) |
| RTX PRO 4500 (Blackwell) | `g7.2xlarge` (2.52), `g7.8xlarge` (4.09) |
| L4 24 GB | `g6.xlarge` (0.80) |
| A10G 24 GB | `g5.xlarge` (1.01) |
| T4 16 GB, V100 | `g4dn`, `p3`: no BF16, which the model's mixed precision uses |

The pipeline uses about 11 GB of GPU memory (Coiled metrics, L40S, 12-step run), so
every GPU with 16 GB or more fits. L4 and A10G have about 1/3 and 1/5 of the L40S's BF16
compute; a 12-step forecast is estimated at 2-3 min on them (not measured), which still
fits the 5-min cycle but adds 1.5-2 min of latency. The same L40S on a smaller instance
(`g6e.4xlarge`, $1.98/h) costs 56% less than `g6e.8xlarge` at the same speed.

**Capacity on 2026-11-09 (us-east-1):** capacity changes from minute to minute.

| Time (UTC) | Result |
|---|---|
| 20:00, 20:01 | `p5.4xlarge` only: `InsufficientInstanceCapacity` in every zone (a to f) |
| 20:03 | 6-type list: got `g7e.8xlarge` (failed later, see the timing log) |
| 20:19 | same 6-type list: every type full |
| 20:20 | same list, first retry: got `g7e.8xlarge` again (VM lost, no keepalive) |
| 20:35 | 10-type list (below), first try: got `g6e.8xlarge`; this is the running VM |

## Run on Coiled

See [Coiled GPU clusters](https://docs.coiled.io/user_guide/clusters/gpu.html). Use the
`earthmover-devs` workspace. Its default region is us-west-2, so always pass
`--region us-east-1`.

The Docker image is not in a registry. `scripts/coiled_bootstrap.sh` starts from the
public NGC base image, repeats the Dockerfile's pip installs, and then runs the pipeline.
It skips the installs when they are already done on the VM.

### Default deployment: `g6e.4xlarge`

**Default and most preferred instance: `g6e.4xlarge`** (1x L40S 48 GB, 16 vCPU / 128 GB,
$1.98/h). It runs a forecast as fast as `g6e.8xlarge` (44.2 s against 45.0 s) at 44% of
the price; see the timing log.

| | |
|---|---|
| Cluster name | `stormscope-us-gpu`, workspace `earthmover-devs` |
| Status | stopped since 2026-11-10 ~06:20 UTC for the GPU benchmark. Ran continuously on a `g6e.8xlarge` (cluster 2352507) from 2026-11-09 21:10 UTC. |
| Job | continuous: a 12-step forecast per 5-min GOES scan, published to `nvidia/sc26-chicago-stormscope_us-booth` |
| Keepalive | 4 h after the command ends; the continuous loop does not end, so the VM runs until it is stopped |
| Stop | `uv run coiled cluster stop --workspace earthmover-devs stormscope-us-gpu` |
| Logs | `uv run coiled logs --workspace earthmover-devs --cluster stormscope-us-gpu --label none` |

### Step 1: get a GPU VM

List `g6e.4xlarge` first, then fallbacks. Coiled uses the next one if AWS has no
capacity. If all are full, the command fails without starting a VM (no cost), so retry
in a loop. The fallbacks below are the other L40S sizes (same speed), then faster and
pricier GPUs:

```bash
for n in $(seq 1 14); do
  uv run coiled run --workspace earthmover-devs --name stormscope-us-gpu --region us-east-1 \
    --ami-version DL --keepalive 4h --skip-ssd-mount \
    --vm-type g6e.4xlarge --vm-type g6e.2xlarge --vm-type g6e.8xlarge --vm-type g6e.16xlarge \
    --vm-type g7e.2xlarge --vm-type g7e.4xlarge --vm-type g7e.8xlarge --vm-type p5.4xlarge \
    --container nvcr.io/nvidia/physicsnemo/physicsnemo:26.08 --root --disk-size 200 \
    --docker-shm-size "1 GiB" --file scripts/ --detach \
    -- bash scripts/coiled_bootstrap.sh --n-steps 3 --start-time 2026-11-09T19:00 --publish-target local \
    > run.log 2>&1
  grep -q "VM Type: *[a-z]" run.log && break  # got a VM
  sleep 120
done
```

The command in the loop is a 3-step test into a local store on the VM. It installs the
dependencies and warms the compile cache.

### Step 2: run continuously on that VM

Use the instance type that step 1 got in `--vm-type`. The same `--name` reuses the running VM. `--env` sends the Arraylake token from `.env`
to the VM; it is not stored anywhere. Without `--start-time` the pipeline loops and runs
each new init:

```bash
(set -a; . ./.env; set +a
 uv run coiled run --workspace earthmover-devs --name stormscope-us-gpu --region us-east-1 \
   --ami-version DL --keepalive 4h --skip-ssd-mount --vm-type g6e.4xlarge \
   --container nvcr.io/nvidia/physicsnemo/physicsnemo:26.08 --root --disk-size 200 \
   --docker-shm-size "1 GiB" --file scripts/ --detach \
   --env ARRAYLAKE_API_TOKEN="$ARRAYLAKE_API_TOKEN" \
   -- bash scripts/coiled_bootstrap.sh --n-steps 12 --publish-target arraylake \
      --arraylake-repo nvidia/sc26-chicago-stormscope_us-booth)
```

The repo holds 12 lead steps, so every run must use `--n-steps 12`.

**Always pass `--ami-version DL`.** Blackwell GPUs (`g7e`, `g7`, B200, B300) work only
with NVIDIA's open kernel modules. Coiled's default AMI has the proprietary driver, so
on a `g7e` the kernel logs `NVRM: ... requires use of the NVIDIA open kernel modules`
and `nvidia-smi` finds no devices. The `DL` AMI (Deep Learning Base OSS Nvidia Driver)
works on all GPU types.

**Pass `--keepalive`** (for example `4h`). With `--detach` and no keepalive, Coiled stops
the VM 10 ms after the command exits, and that GPU can be gone on the next launch. It
also stopped the VM while the command was still running: twice it ended during the
bootstrap's first `pip install` (clusters 2352426 and 2355602), but never with a keepalive.
`scripts/coiled_gpu_benchmark.sh` therefore uses `--keepalive 30m` and stops each cluster
itself when the run is done. A
later `coiled run` with the same `--name` reuses the running VM. Stop it with
`uv run coiled cluster stop --workspace earthmover-devs <name>`.

**Pass `--skip-ssd-mount`** on instances with a local NVMe SSD (`g6e`, `g6`, `g5`). On
a `g6e.4xlarge` with the `DL` AMI, Coiled could not format the SSD (`mkfs.xfs: cannot
open /dev/nvme1n1: Device or resource busy`), `/scratch` was missing, and the cluster
stopped with "Software environment exited with error code 1" before the command ran
(2026-11-10, twice). The `g6e.8xlarge` on 2026-11-09 mounted it without problems.

Do not attach to a run VM with `coiled.Cluster(name=...)`. If that VM has stopped, this
call starts a new default Dask cluster (CPU only) under the same name.

If AWS has no capacity or the quota is too low, Coiled returns an error such as
`InsufficientInstanceCapacity` or `VcpuLimitExceeded`.

## Inference timing log

One row per pipeline run on a Coiled VM. The pipeline prints `timing:` (fetch, rollout
plus write, commit) and `step times (<GPU>):`. Step 0 returns the observed analysis frame and does not
call the model. Step 1 is the first model step and includes the `torch.compile` warmup.
"s/step" is the mean of steps 2 and later, the steady state. Full CONUS, `3km_10min_flash`, 1 ensemble
member.

| Date (UTC) | Cluster | Instance | GPU | n_steps | Fetch s | Step 1 s (warmup) | s/step | Commit s | Result |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-09 20:04 | 2352303 | g7e.8xlarge | RTX PRO 6000 Server | 3 | - | - | - | - | failed: default AMI has no open kernel modules, no GPU (fixed with `--ami-version DL`) |
| 2026-11-09 20:20 | 2352426 | g7e.8xlarge | RTX PRO 6000 Server | 3 | - | - | - | - | failed: bootstrap exited after the first pip install, cause not logged; VM stopped (no keepalive) |
| 2026-11-09 20:41 | 2352507 | g6e.8xlarge | L40S 48 GB | 3 | 7.0 | 18.4 | 3.9 | 0.0 | OK, local store; total 33.6 s; init 19:00 |
| 2026-11-09 21:00 | 2352507 | g6e.8xlarge | L40S 48 GB | 12 | 6.8 | 9.2 | 3.7 (3.3 from step 4) | 0.7 | OK, Arraylake `nvidia/sc26-chicago-stormscope_us-booth` commit `EYATA1996D8V8D11KM3G`; total 55.7 s; init 20:30; same VM as the row above, so the compile cache was warm |
| 2026-11-09 21:11–21:26 | 2352507 | g6e.8xlarge | L40S 48 GB | 12 | 3.3–6.4 | - | 3.4–4.0 (rollout+write 40.4–48.0 s / 12) | 0.5–0.7 | OK, continuous, inits 21:05–21:20 every 5 min; total 44.3–54.9 s; published ~6 min after slot time |
| 2026-11-10 08:15–08:30 | 2355678 | g6e.4xlarge | L40S 48 GB | 12 | 3.7 | - | 3.3 (rollout+write 40.0 s / 12) | 0.6 | OK, benchmark, 4 live inits, mean of the last 3: total 44.2 s (first, cold compile cache: 62.2 s); $1.98/h, $0.024 per forecast; same speed as g6e.8xlarge (45.0 s) at 44% of the price |
| TODO | | `g6e.2xlarge` | L40S 48 GB | 12 | | | | | to check: same GPU, 8 vCPU / 64 GB RAM, $2.24/h (more than g6e.4xlarge at $1.98/h) |
| TODO | | `g6e.xlarge` | L40S 48 GB | 12 | | | | | to check: same GPU, $1.86/h (−59%); 4 vCPU / 32 GB RAM may slow fetch or upload |
| TODO | | `g6.xlarge` | L4 24 GB | 12 | | | | | to check: $0.80/h (−82%); estimated 2–2.5 min per forecast |
| TODO | | `g5.xlarge` | A10G 24 GB | 12 | | | | | to check: $1.01/h (−78%); estimated 2–3 min per forecast |

## Sources

- https://instances.vantage.sh/aws/ec2/p6-b200.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p6-b300.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5en.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5.4xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g7e.2xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g7e.8xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g6e.xlarge?region=us-east-1
