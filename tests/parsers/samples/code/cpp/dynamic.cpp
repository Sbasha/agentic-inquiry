#include <functional>
#include <string>

#include "simple.cpp"

std::function<std::string()> load_action(const std::string& name) {
    if (name == "summarize") {
        return summarize;
    }
    return []() { return std::string("unknown"); };
}

std::string run_dynamic(const std::string& name) {
    auto fn = load_action(name);
    return "dynamic:" + fn();
}
