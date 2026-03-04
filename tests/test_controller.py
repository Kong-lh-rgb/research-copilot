from app.graph.nodes.controller import controller_node
import logging
logging.basicConfig(level=logging.INFO)
def test_controller_node():
    state = {
        "user_input": "查询比亚迪和小米汽车的财报并作报告"
    }
    result = controller_node(state)
    print(result)

if __name__ == "__main__":
    test_controller_node()