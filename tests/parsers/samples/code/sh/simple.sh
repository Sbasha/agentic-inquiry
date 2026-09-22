# shellcheck source=./complex.sh
. ./complex.sh

simple_summary() {
    local baseline
    baseline=$(complex_distance 10 3)
    local rms
    rms=$(complex_rms 1 2 3)
    echo "baseline=${baseline}, rms=${rms}"
}
