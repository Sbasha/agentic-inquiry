local simple = require("simple")

local dynamic = {}

local registry = {
    summarize = simple.summarize
}

function dynamic.run(name)
    name = name or "summarize"
    local action = registry[name]
    if not action then
        return "unknown"
    end
    return "dynamic:" .. action()
end

return dynamic
