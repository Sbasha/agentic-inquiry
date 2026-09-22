module Dynamic exposing (run)

import Simple


type alias Registry =
    { summarize : () -> String }


registry : Registry
registry =
    { summarize = \_ -> Simple.summarize }


run : String -> String
run name =
    case name of
        "summarize" ->
            "dynamic:" ++ registry.summarize ()

        _ ->
            "unknown"
