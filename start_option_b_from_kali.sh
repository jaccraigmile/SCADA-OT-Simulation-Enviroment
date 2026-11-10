#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: start_option_b_from_kali.sh {start|stop|restart|status}

Optional environment overrides:
  SIMULATOR_SSH_TARGET  SSH target for the simulator (default: otlab@10.77.20.10)
  CONTROLLER_SSH_TARGET SSH target for the controller (default: otlab@10.77.10.10)
  SSH_IDENTITY_FILE     Optional private key to pass to ssh with -i
EOF
}

if [[ $# -ne 1 ]]; then
    usage >&2
    exit 2
fi

action=$1
case "$action" in
    start|stop|restart|status) ;;
    *)
        usage >&2
        exit 2
        ;;
esac

simulator_target=${SIMULATOR_SSH_TARGET:-otlab@10.77.20.10}
controller_target=${CONTROLLER_SSH_TARGET:-otlab@10.77.10.10}
ssh_options=(-o BatchMode=yes -o ConnectTimeout=5)
if [[ -n ${SSH_IDENTITY_FILE:-} ]]; then
    ssh_options+=(-i "$SSH_IDENTITY_FILE")
fi

run_remote() {
    local target=$1
    local unit=$2
    local remote_action=$3
    ssh "${ssh_options[@]}" "$target" \
        "sudo -n /usr/bin/systemctl $remote_action $unit"
}

case "$action" in
    start)
        run_remote "$simulator_target" factoryio-simulator.service start
        run_remote "$controller_target" factoryio-controller.service start
        ;;
    stop)
        run_remote "$controller_target" factoryio-controller.service stop
        run_remote "$simulator_target" factoryio-simulator.service stop
        ;;
    restart)
        run_remote "$controller_target" factoryio-controller.service stop
        run_remote "$simulator_target" factoryio-simulator.service restart
        run_remote "$controller_target" factoryio-controller.service start
        ;;
    status)
        status=0
        run_remote "$simulator_target" factoryio-simulator.service is-active || status=1
        run_remote "$controller_target" factoryio-controller.service is-active || status=1
        exit "$status"
        ;;
esac
