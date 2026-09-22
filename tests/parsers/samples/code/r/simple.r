run_simple <- function() {
  baseline <- complex_distance(10, 3, scale = 0.8)
  rms <- complex_root_mean_square(c(1, 2, 3))
  list(baseline = baseline, rms = rms)
}

summarize <- function() {
  metrics <- run_simple()
  sprintf('baseline=%.2f, rms=%.2f', metrics$baseline, metrics$rms)
}
