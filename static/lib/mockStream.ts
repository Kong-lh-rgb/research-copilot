import { StreamEvent } from "@/lib/types";

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

export async function* mockStream(query: string): AsyncGenerator<StreamEvent> {
  yield { type: "start", query };
  await delay(400);
  yield { type: "log", message: "理解用户问题", level: "info" };
  await delay(300);
  yield { type: "log", message: "拆解任务" };
  await delay(300);
  yield { type: "task_start", task_id: "task_1", description: "搜索股票代码" };
  await delay(300);
  yield { type: "task_running", task_id: "task_1" };
  await delay(300);
  yield { type: "tool_call", tool_name: "search_stock_code", arguments: "{\"name\":\"比亚迪\"}" };
  await delay(500);
  yield { type: "tool_result", tool_name: "search_stock_code", result: "股票代码: 002594" };
  await delay(300);
  yield { type: "task_complete", task_id: "task_1" };
  await delay(300);
  yield { type: "task_start", task_id: "task_2", description: "查询股价" };
  await delay(300);
  yield { type: "task_running", task_id: "task_2" };
  await delay(300);
  yield { type: "tool_call", tool_name: "get_stock_spot", arguments: "{\"code\":\"002594\"}" };
  await delay(500);
  yield { type: "tool_result", tool_name: "get_stock_spot", result: "现价: 205.30" };
  await delay(300);
  yield { type: "task_complete", task_id: "task_2" };
  await delay(400);
  yield { type: "log", message: "生成最终报告" };
  await delay(600);
  yield {
    type: "final",
    reply:
      "# 比亚迪股价报告\n\n- 当前股价: **205.30**\n- 近 5 日趋势: 稳中有升\n\n## 结论\n短期保持关注，结合成交量进一步观察。",
  };
  await delay(300);
  yield { type: "end" };
}
