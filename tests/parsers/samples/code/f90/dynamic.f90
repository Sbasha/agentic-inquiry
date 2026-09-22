program dynamic_metrics
  use simple_metrics
  implicit none
  real :: baseline, rms
  call summarize(baseline, rms)
  print *, 'baseline=', baseline, 'rms=', rms
end program dynamic_metrics
