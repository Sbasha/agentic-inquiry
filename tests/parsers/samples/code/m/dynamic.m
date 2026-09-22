function output = dynamicRun(name)
if nargin == 0
    name = 'summarize';
end
if strcmp(name, 'summarize')
    output = ['dynamic:' SimpleMetrics.summarize()];
else
    output = 'unknown';
end
end
