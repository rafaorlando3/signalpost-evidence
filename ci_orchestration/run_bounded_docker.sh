#!/usr/bin/env bash
# Job-local bounded Docker runner with deterministic stop/kill/inspect closure before output consumption (CI-V1-06).
set -euo pipefail

CONTAINER_NAME=""
TIMEOUT_SECONDS=""
ALLOW_EXIT_CODES="0"
STATE_JSON=""
STDOUT_FILE=""
STDERR_FILE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --name)
      CONTAINER_NAME="$2"
      shift 2
      ;;
    --timeout-seconds)
      TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --allow-exit-codes)
      ALLOW_EXIT_CODES="$2"
      shift 2
      ;;
    --state-json)
      STATE_JSON="$2"
      shift 2
      ;;
    --stdout-file)
      STDOUT_FILE="$2"
      shift 2
      ;;
    --stderr-file)
      STDERR_FILE="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "Unknown option in run_bounded_docker.sh: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "${CONTAINER_NAME}" ] || [ -z "${TIMEOUT_SECONDS}" ] || [ -z "${STATE_JSON}" ] || [ -z "${STDOUT_FILE}" ] || [ -z "${STDERR_FILE}" ]; then
  echo "Missing required arguments to run_bounded_docker.sh" >&2
  exit 1
fi

cleanup_if_leftover() {
  if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
    docker stop -t 5 "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker kill "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker wait "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
}

cleanup_if_leftover
trap cleanup_if_leftover EXIT INT TERM

START_EPOCH="$(date -u +%s)"
START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

set +e
timeout --signal=TERM --kill-after=15s "${TIMEOUT_SECONDS}s" \
  docker run --name "${CONTAINER_NAME}" "$@" \
  > "${STDOUT_FILE}" 2> "${STDERR_FILE}"
CLIENT_EXIT_CODE=$?
set -e

TIMED_OUT="false"
if [ "${CLIENT_EXIT_CODE}" -eq 124 ] || [ "${CLIENT_EXIT_CODE}" -eq 137 ]; then
  TIMED_OUT="true"
fi

# Ensure the subject container itself has stopped before inspecting or reading outputs
if docker container inspect "${CONTAINER_NAME}" >/dev/null 2>&1; then
  RUNNING_NOW="$(docker container inspect --format '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || echo unknown)"
  if [ "${RUNNING_NOW}" = "true" ]; then
    docker stop -t 10 "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker kill "${CONTAINER_NAME}" >/dev/null 2>&1 || true
    docker wait "${CONTAINER_NAME}" >/dev/null 2>&1 || true
  fi
  FINAL_RUNNING="$(docker container inspect --format '{{.State.Running}}' "${CONTAINER_NAME}" 2>/dev/null || echo unknown)"
  FINAL_STATUS="$(docker container inspect --format '{{.State.Status}}' "${CONTAINER_NAME}" 2>/dev/null || echo unknown)"
  CONTAINER_EXIT_CODE="$(docker container inspect --format '{{.State.ExitCode}}' "${CONTAINER_NAME}" 2>/dev/null || echo -1)"
  OOM_KILLED="$(docker container inspect --format '{{.State.OOMKilled}}' "${CONTAINER_NAME}" 2>/dev/null || echo unknown)"
  FINISHED_AT="$(docker container inspect --format '{{.State.FinishedAt}}' "${CONTAINER_NAME}" 2>/dev/null || echo unknown)"
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
else
  FINAL_RUNNING="missing"
  FINAL_STATUS="missing"
  CONTAINER_EXIT_CODE="${CLIENT_EXIT_CODE}"
  OOM_KILLED="unknown"
  FINISHED_AT="unknown"
fi

END_EPOCH="$(date -u +%s)"
END_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ELAPSED_SECONDS="$((END_EPOCH - START_EPOCH))"

CLOSURE_VERIFIED="false"
if [ "${FINAL_RUNNING}" = "false" ] && { [ "${FINAL_STATUS}" = "exited" ] || [ "${FINAL_STATUS}" = "dead" ]; }; then
  CLOSURE_VERIFIED="true"
fi

python3 -B -c '
import json, sys
(
    state_json,
    cname,
    client_code,
    container_code,
    timed_out,
    closure_verified,
    final_running,
    final_status,
    oom_killed,
    start_utc,
    end_utc,
    finished_at,
    elapsed,
    allow_codes,
) = sys.argv[1:]
allowed = [int(x.strip()) for x in allow_codes.split(",") if x.strip()]
c_exit = int(container_code)
cl_exit = int(client_code)
is_timed_out = timed_out == "true"
is_closed = closure_verified == "true"
exit_acceptable = (not is_timed_out) and is_closed and (c_exit in allowed) and (cl_exit in allowed)
payload = {
    "container_name": cname,
    "client_exit_code": cl_exit,
    "cli_exit_code": c_exit,
    "container_exit_code": c_exit,
    "allowed_exit_codes": allowed,
    "exit_code_acceptable": exit_acceptable,
    "timed_out": is_timed_out,
    "container_closure_verified": is_closed,
    "final_state_running": final_running,
    "final_state_status": final_status,
    "oom_killed": oom_killed == "true",
    "started_at_utc": start_utc,
    "finished_at_utc": end_utc,
    "container_finished_at": finished_at,
    "wall_clock_seconds": int(elapsed),
}
with open(state_json, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
    fh.write("\n")
if not exit_acceptable:
    raise SystemExit(
        f"Container {cname} failed bounded execution/closure check: "
        f"client_exit={cl_exit} container_exit={c_exit} timed_out={is_timed_out} closed={is_closed}"
    )
' \
  "${STATE_JSON}" \
  "${CONTAINER_NAME}" \
  "${CLIENT_EXIT_CODE}" \
  "${CONTAINER_EXIT_CODE}" \
  "${TIMED_OUT}" \
  "${CLOSURE_VERIFIED}" \
  "${FINAL_RUNNING}" \
  "${FINAL_STATUS}" \
  "${OOM_KILLED}" \
  "${START_UTC}" \
  "${END_UTC}" \
  "${FINISHED_AT}" \
  "${ELAPSED_SECONDS}" \
  "${ALLOW_EXIT_CODES}"
