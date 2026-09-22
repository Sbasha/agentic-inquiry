import React from "react";

export const DynamicGateway = React.lazy(() =>
    import("./simple").then(module => ({
        default: module.SimplePanel,
    }))
);

export const runDynamic = async (name: string = "SimplePanel") => {
    if (name !== "SimplePanel") {
        return "dynamic:unknown";
    }
    const module = await import("./simple");
    const Component = module.SimplePanel;
    return `dynamic:${Component.name}`;
};
