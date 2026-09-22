module complex_metrics
  implicit none
contains
  function distance(a, b) result(res)
    integer, intent(in) :: a, b
    real :: res
    res = abs(a - b)
  end function distance

  function root_mean_square(values, count) result(res)
    real, intent(in) :: values(*)
    integer, intent(in) :: count
    real :: total
    integer :: i
    if (count == 0) then
      res = 0.0
      return
    end if
    total = 0.0
    do i = 1, count
      total = total + values(i) * values(i)
    end do
    res = sqrt(total / count)
  end function root_mean_square
end module complex_metrics
