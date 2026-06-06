#!/usr/bin/env python
"""Record a teleoperation dataset for ONE skill, via LeRobot's recorder.

This is a thin convenience wrapper that prints the exact `lerobot-record` command for a
given skill (so the whole team uses consistent dataset names + task strings). Recording
itself is done by LeRobot.

    python scripts/record_demos.py dispense_pills --episodes 60
"""

from __future__ import annotations

import argparse

from nursearm import config


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("skill")
    ap.add_argument("--episodes", type=int, default=60)
    ap.add_argument("--hf-user", default="YOUR_HF_USERNAME")
    args = ap.parse_args()

    rc = config.robot_config()
    skills = config.skills_config().get("skills", {})
    task = skills.get(args.skill, {}).get("task", f"perform the {args.skill} task")

    cmd = f"""lerobot-record \\
  --robot.type=so101_follower --robot.port={rc.get('follower_port', '/dev/ttyACM0')} --robot.id={rc.get('follower_id', 'follower')} \\
  --teleop.type=so101_leader  --teleop.port={rc.get('leader_port', '/dev/ttyACM1')}  --teleop.id={rc.get('leader_id', 'leader')} \\
  --robot.cameras="{rc.get('camera_arg')}" \\
  --dataset.repo_id={args.hf_user}/nursearm_{args.skill} \\
  --dataset.single_task="{task}" \\
  --dataset.num_episodes={args.episodes} \\
  --dataset.episode_time_s=30 \\
  --display_data=true"""
    print("# Run this to record demos for", args.skill, ":\n")
    print(cmd)


if __name__ == "__main__":
    main()
