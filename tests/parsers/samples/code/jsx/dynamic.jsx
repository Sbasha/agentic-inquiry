import React from "react";

export const DynamicGateway = React.lazy(() =>
    import("./simple").then(module => ({
        default: module.SimplePanel,
    }))
);
