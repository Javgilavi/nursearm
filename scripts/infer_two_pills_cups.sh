#!/usr/bin/env bash
# Run the two_pills_cups ACT policy on a real SO-101 follower.
#
# This is the warm-start + augmentation model (107 episodes, 30k steps) that was
# published to the Hub as Laniakea2002/act_sort and trained into
#   outputs/train/act_two_pills_107_warm_aug/
#
# Usage:
#   ./infer_two_pills_cups.sh                 # Hub model Laniakea2002/act_sort (default)
#   ./infer_two_pills_cups.sh 030000          # LOCAL checkpoint of the new run, by step
#   ./infer_two_pills_cups.sh 015000          # ... e.g. compare 15k vs 25k vs 30k
#   ./infer_two_pills_cups.sh last            # local "last" symlink (== 30k)
#   ./infer_two_pills_cups.sh user/model      # any Hugging Face repo id
#
# Override any hardware value inline, e.g.:
#   ROBOT_PORT=/dev/ttyACM2 ./infer_two_pills_cups.sh
set -e

# ============================================================================
#  CONFIG  —  override as env vars if your hardware differs
# ============================================================================
# Default policy: the published Hub repo (auto-downloaded). A positional arg
# ($1) overrides this with either a Hub id or a local checkpoint step name.
POLICY="${POLICY:-Laniakea2002/act_sort}"

# Local checkpoints of the new run live here (used when $1 is a step like 030000).
CKPT_DIR="${CKPT_DIR:-outputs/train/act_two_pills_107_warm_aug/checkpoints}"

# Where lerobot is installed (must contain .venv).
LEROBOT_DIR="${LEROBOT_DIR:-$HOME/lerobot}"

# Robot serial port. Follower is on ACM1 here (ACM0 is the leader).
ROBOT_PORT="${ROBOT_PORT:-/dev/ttyACM1}"

# Calibration id: a file <ROBOT_ID>.json must exist for this arm.
ROBOT_ID="${ROBOT_ID:-Follower}"

# Cameras  -> find serials/paths with: lerobot-find-cameras
# The policy was trained on TWO cameras named 'wrist' and 'front' — keep those
# names and resolutions; only point them at YOUR devices.
WRIST_CAM="${WRIST_CAM:-/dev/v4l/by-id/usb-HBV_HD_CAMERA_HBV_HD_CAMERA-video-index0}"
FRONT_REALSENSE_SERIAL="${FRONT_REALSENSE_SERIAL:-218622275778}"

# How long to run, in seconds.
DURATION="${DURATION:-60}"
# ============================================================================

cd "$LEROBOT_DIR"
source .venv/bin/activate

# Positional arg overrides POLICY (local checkpoint step OR Hub repo id).
ARG="${1:-$POLICY}"

# "user/model" form that isn't a local path -> Hub repo id (downloaded).
# Otherwise treat $ARG as a checkpoint step name under CKPT_DIR.
if [[ "$ARG" == */* && ! -e "$ARG" ]]; then
  POLICY_PATH="$ARG"
  echo "Running policy from Hugging Face Hub: $POLICY_PATH"
else
  POLICY_PATH="${CKPT_DIR}/${ARG}/pretrained_model"
  if [ ! -d "$POLICY_PATH" ]; then
    echo "ERROR: checkpoint not found: $POLICY_PATH"
    echo "Available local checkpoints:"
    ls -1 "$CKPT_DIR" 2>/dev/null || echo "  (none)"
    echo "Or pass a Hub repo id, e.g.: ./infer_two_pills_cups.sh Laniakea2002/act_sort"
    exit 1
  fi
  echo "Running policy from local checkpoint: $POLICY_PATH"
fi

# Pre-flight: free cameras + reset RealSense (avoids post-crash timeout).
pkill -9 -f lerobot-record  2>/dev/null || true
pkill -9 -f lerobot-rollout 2>/dev/null || true
pkill -9 -f ffplay          2>/dev/null || true
sleep 1
uv run python -c "import pyrealsense2 as rs; [d.hardware_reset() for d in rs.context().query_devices()]" 2>/dev/null || true
sleep 6

# Camera names/resolutions MUST match the training dataset (wrist + front).
CAMERAS="{wrist: {type: opencv, index_or_path: ${WRIST_CAM}, width: 640, height: 480, fps: 15, fourcc: MJPG}, front: {type: intelrealsense, serial_number_or_name: ${FRONT_REALSENSE_SERIAL}, width: 424, height: 240, fps: 15}}"

# temporal_ensemble_coeff -> smooth multi-step motion. n_action_steps MUST be 1
# whenever temporal ensembling is on (ACT requirement).
lerobot-rollout \
  --strategy.type=base \
  --policy.path="$POLICY_PATH" \
  --policy.temporal_ensemble_coeff=0.01 \
  --policy.n_action_steps=1 \
  --robot.type=so101_follower \
  --robot.port="$ROBOT_PORT" \
  --robot.id="$ROBOT_ID" \
  --robot.cameras="$CAMERAS" \
  --task="Sort two mock pills, green to green cup and black to black cup" \
  --fps=15 \
  --duration="$DURATION"
