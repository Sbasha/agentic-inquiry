module Dynamic (run) where

import Simple (summarize)

run :: String -> String
run "summarize" = "dynamic:" ++ summarize
run _ = "unknown"
