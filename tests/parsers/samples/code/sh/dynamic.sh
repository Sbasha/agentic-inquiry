# shellcheck source=./simple.sh
. ./simple.sh

run_dynamic() {
    local action=${1:-simple_summary}
    if declare -F "$action" >/dev/null 2>&1; then
        echo "dynamic:$("$action")"
    else
        echo "unknown"
    fi
}
