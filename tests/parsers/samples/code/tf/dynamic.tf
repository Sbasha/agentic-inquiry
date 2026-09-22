
resource "null_resource" "dynamic_summary" {
  triggers = {
    summary = "dynamic:${local.baseline_distance}"
  }
}
