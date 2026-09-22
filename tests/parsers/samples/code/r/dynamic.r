run_dynamic <- function(name = 'summarize') {
  if (!exists(name)) {
    return('unknown')
  }
  paste0('dynamic:', do.call(name, list()))
}
