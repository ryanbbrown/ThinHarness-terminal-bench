import { createCodingTools } from "/opt/pi-subscription/node_modules/@earendil-works/pi-coding-agent/dist/index.js";

const tools = createCodingTools("/app");
process.stdout.write(JSON.stringify({
  root: "/app",
  tools: tools.map((tool) => ({
    name: tool.name,
    description: tool.description,
    parameters: tool.parameters,
  })),
}, null, 2) + "\n");
