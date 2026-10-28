import { loadConfig } from "./config.js";
import { initAuthToken } from "./auth.js";
import { McpManager } from "./mcp/manager.js";
import { CoreServer } from "./server.js";
import { captureSupervisor } from "./capture/supervisor.js";

async function main() {
  const config = loadConfig();
  const token = initAuthToken();

  console.log("  𒀭 Enheduanna Integration Core Service");
  console.log(`  • Host: http://${config.server.host}:${config.server.port}`);
  console.log(`  • Model: ${config.model.modelName} (${config.model.provider})`);
  console.log("------------------------------------------------------------------");

  const mcpManager = new McpManager(config);
  await mcpManager.init();

  const server = new CoreServer(config, mcpManager);
  await server.listen();

  console.log(`  🚀 Enheduanna Server is LIVE at http://${config.server.host}:${config.server.port}`);
  console.log(`  • Dashboard: http://${config.server.host}:${config.server.port}/?token=${token}`);
  console.log("------------------------------------------------------------------");

  const shutdown = async () => {
    console.log("\n[Enheduanna] Shutting down gracefully...");
    captureSupervisor.destroy();
    await mcpManager.close();
    await server.close();
    process.exit(0);
  };

  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((err) => {
  console.error("[Fatal Error]", err);
  process.exit(1);
});
