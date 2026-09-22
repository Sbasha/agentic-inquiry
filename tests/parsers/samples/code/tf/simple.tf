
output "metrics" {
  value = {
    baseline = local.baseline_distance
    rms      = sqrt(sum([for v in local.rms_values : v * v]) / length(local.rms_values))
  }
}
