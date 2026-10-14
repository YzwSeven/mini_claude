"""第五章：配置 GPT 的思考强度。"""


def get_gpt_reasoning_effort(thinking=False):
    """GPT 协议适配：默认 low，加 --thinking 时改为 high。"""
    # 这是条件表达式：thinking 为 True 选 high，否则选 low。
    # low 仍允许模型思考；这里的开关表示加强思考，不是完全关闭/开启。
    return "high" if thinking else "low"


def is_gpt_55(model):
    """本次核对的是 GPT-5.5 普通版及日期快照，不猜其他模型的能力。"""
    return model == "gpt-5.5" or model.startswith("gpt-5.5-20")
