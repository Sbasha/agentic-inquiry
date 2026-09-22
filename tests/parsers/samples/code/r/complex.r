complex_distance <- function(a, b, scale = 1.0) {
  abs(a - b) * scale
}

complex_root_mean_square <- function(values) {
  if (length(values) == 0) {
    return(0)
  }
  total <- sum(values ^ 2)
  sqrt(total / length(values))
}
