from langgraph.graph import END,START,StateGraph
from app.graph.nodes.controller import controller_node
from app.graph.nodes.simple_chat import simple_chat_node
from app.graph.nodes.planner import planner_node
from app.graph.nodes.reviewer import reviewer_node
from app.graph.nodes.worker import worker_node
from app.graph.state import AgentState
from langgraph.types import Send

def router_after_controller(state:AgentState)->str:
    next_action = state.get("next_action","")
    if next_action == "complex_research":
        return "planner"
    else:
        return "simple_chat"
    
def distribute_tasks(state: AgentState):
    """
    任务分发器：扫描任务池，并发拉起 Worker，或收集结果交给 Reviewer
    """
    tasks = state.get("tasks", {})
    sends = []
    all_completed = True
    
    for task_id, task_node in tasks.items():
        if task_node.status != "completed":
            all_completed = False
            

        if task_node.status == "pending" and all(
            tasks[dep].status=="completed" for dep in task_node.dependencies
        ):
            sends.append(Send("worker", {"current_task_id": task_id}))
            
    
    if all_completed and tasks:
        return "reviewer"
        

    if sends:
        return sends
        

    return END
    
def build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("controller", controller_node)
    graph.add_node("simple_chat", simple_chat_node)
    graph.add_node("planner", planner_node)
    graph.add_node("worker", worker_node)
    graph.add_node("reviewer", reviewer_node)
    graph.set_entry_node("controller")

    graph.add_conditional_edge(
        "controller",
        router_after_controller,
        {
            "simple_chat": "simple_chat",
            "planner": "planner"
        }
    )
    
    graph.add_conditional_edges(
        "planner",
        distribute_tasks,
        ["worker", "reviewer"]
    )

    graph.add_conditional_edges(
        "worker",
        distribute_tasks,
        ["worker", "reviewer"]
    )


    graph.add_edge("reviewer", END)
    graph.add_edge("simple_chat", END)

    return graph

