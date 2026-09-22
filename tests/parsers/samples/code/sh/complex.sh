complex_distance() {
    local a=$1
    local b=$2
    if [ "$a" -gt "$b" ]; then
        echo $((a - b))
    else
        echo $((b - a))
    fi
}

complex_rms() {
    local values=("$@")
    local total=0
    local count=${#values[@]}
    if [ "$count" -eq 0 ]; then
        echo 0
        return
    fi
    for value in "${values[@]}"; do
        total=$((total + value * value))
    done
    printf "%.2f" "$(echo "scale=6; sqrt($total / $count)" | bc)"
}
