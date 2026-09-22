let run name =
  match name with
  | "summarize" -> "dynamic:" ^ Simple.summarize ()
  | _ -> "unknown"
