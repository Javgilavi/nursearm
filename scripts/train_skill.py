#!/usr/bin/env python
"""Print the `lerobot-train` command to train an ACT policy for ONE skill.

    python scripts/train_skill.py sort_pills --steps 60000

Training is done by LeRobot. This keeps hyper-params + output paths consistent across
the team and matches the policy_path the skill registry expects (config/skills.yaml).
"""

from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("skill")
    ap.add_argument("--policy", default="act")
    ap.add_argument("--steps", type=int, default=60000)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--hf-user", default="YOUR_HF_USERNAME")
    args = ap.parse_args()

    out = f"outputs/train/{args.policy}_{args.skill}"
    cmd = f"""lerobot-train \\
  --dataset.repo_id={args.hf_user}/nursearm_{args.skill} \\
  --policy.type={args.policy} \\
  --policy.device=cuda \\
  --batch_size={args.batch_size} \\
  --steps={args.steps} \\
  --save_freq=10000 \\
  --output_dir={out} \\
  --job_name={args.policy}_{args.skill}"""
    print("# Train", args.skill, ":\n")
    print(cmd)
    print(f"\n# Then set policy_path for '{args.skill}' in config/skills.yaml to:")
    print(f"#   {out}/checkpoints/{args.steps:06d}/pretrained_model")
if __name__ == "__main__":
    main()
