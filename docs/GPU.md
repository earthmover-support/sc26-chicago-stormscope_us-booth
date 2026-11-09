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

## Test availability

Start a VM, run `nvidia-smi`, and stop the VM:

```bash
uv run coiled run --region us-east-1 --vm-type p5.4xlarge -- nvidia-smi
```

If AWS has no capacity or the quota is too low, Coiled returns an error such as
`InsufficientInstanceCapacity` or `VcpuLimitExceeded`.

## Sources

- https://instances.vantage.sh/aws/ec2/p6-b200.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p6-b300.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5en.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5.48xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/p5.4xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g7e.2xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g7e.8xlarge?region=us-east-1
- https://instances.vantage.sh/aws/ec2/g6e.xlarge?region=us-east-1
