package samples

var registry = map[string]func() string{
	"summarize": Summarize,
}

func RunDynamic(name string) string {
	if action, ok := registry[name]; ok {
		return "dynamic:" + action()
	}
	return "unknown"
}
