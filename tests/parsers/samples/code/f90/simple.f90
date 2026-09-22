module simple_metrics
  use complex_metrics
  implicit none
contains
  subroutine summarize(baseline, rms)
    real, intent(out) :: baseline, rms
    real :: values(3)
    values = (/ 1.0, 2.0, 3.0 /)
    baseline = distance(10, 3)
    rms = root_mean_square(values, 3)
  end subroutine summarize
end module simple_metrics
