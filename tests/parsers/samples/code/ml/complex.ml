let distance a b = abs (a - b)

let root_mean_square values =
  match values with
  | [] -> 0.
  | _ ->
      let total = List.fold_left (fun acc v -> acc +. float_of_int v *. float_of_int v) 0. values in
      sqrt (total /. float_of_int (List.length values))
