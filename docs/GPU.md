# GPU options in AWS us-east-1

The pipeline runs in AWS **us-east-1**. This is the same region as the NOAA GOES-19
bucket (`noaa-goes19`), so there is no cross-region transfer (see `AGENTS.md`).
GPU VMs are started with [Coiled](https://docs.coiled.io) (dev dependency). The Coiled
workspace `aaron_spring` uses the AWS backend in `us-east-1`.

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
| A10G 24 GB, L4 24 GB, T4, V100 | `g5`, `g6`, `g4dn`, `p3`: too slow or too little memory for this model |

**Capacity on 2026-11-09:** `p5.4xlarge` returned `InsufficientInstanceCapacity` in
every us-east-1 zone (a to f), in two tries.

## Run on Coiled

See [Coiled GPU clusters](https://docs.coiled.io/user_guide/clusters/gpu.html). Use the
`earthmover-devs` workspace. Its default region is us-west-2, so always pass
`--region us-east-1`.

The Docker image is not in a registry. `scripts/coiled_bootstrap.sh` starts from the
public NGC base image, repeats the Dockerfile's pip installs, and then runs the pipeline.
Give several `--vm-type` options, fastest first. Coiled uses the next one if AWS has no
capacity:

```bash
uv run coiled run --workspace earthmover-devs --region us-east-1 --ami-version DL \
  --vm-type p5.4xlarge --vm-type g7e.8xlarge --vm-type g7e.4xlarge --vm-type g7e.2xlarge \
  --vm-type g6e.8xlarge --vm-type g6e.4xlarge \
  --container nvcr.io/nvidia/physicsnemo/physicsnemo:26.08 --root --disk-size 200 \
  --docker-shm-size "1 GiB" --file scripts/ --detach --keepalive 4h \
  -- bash scripts/coiled_bootstrap.sh --n-steps 3 --start-time 2026-11-09T19:00 --publish-target local
```

**Always pass `--ami-version DL`.** Blackwell GPUs (`g7e`, `g7`, B200, B300) work only
with NVIDIA's open kernel modules. Coiled's default AMI has the proprietary driver, so
on a `g7e` the kernel logs `NVRM: ... requires use of the NVIDIA open kernel modules`
and `nvidia-smi` finds no devices. The `DL` AMI (Deep Learning Base OSS Nvidia Driver)
works on all GPU types.

**Pass `--keepalive`** (for example `4h`). With `--detach` and no keepalive, Coiled stops
the VM 10 ms after the command exits, and that GPU can be gone on the next launch. A
later `coiled run` with the same `--name` reuses the running VM. Stop it with
`uv run coiled cluster stop --workspace earthmover-devs <name>`.

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

## Sources

- https://instances.vantage.sh/aws/ec2/p6-b200.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p6-b300.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5en.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5.4xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g7e.2xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g7e.8xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g6e.xlarge?region=us-east-1
