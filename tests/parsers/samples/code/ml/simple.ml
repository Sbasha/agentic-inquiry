let summarize () =
  let baseline = Complex.distance 10 3 in
  let rms = Complex.root_mean_square [1; 2; 3] in
  Printf.sprintf "baseline=%.2f, rms=%.2f" (float_of_int baseline) rms
