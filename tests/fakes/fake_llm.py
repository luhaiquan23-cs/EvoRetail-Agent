from typing import List, Dict, Any, Optional

class FakeFunction:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments

class FakeToolCall:
    def __init__(self, id: str, name: str, arguments: str):
        self.id = id
        self.function = FakeFunction(name, arguments)

class FakeDelta:
    def __init__(self, content: Optional[str] = None, tool_calls: Optional[List[Any]] = None):
        self.content = content
        self.tool_calls = tool_calls

class FakeChoice:
    def __init__(self, delta: FakeDelta):
        self.delta = delta

class FakeChunk:
    def __init__(self, content: Optional[str] = None, tool_calls: Optional[List[Any]] = None):
        self.choices = [FakeChoice(FakeDelta(content=content, tool_calls=tool_calls))]

class FakeAsyncOpenAIClient:
    """
    用于测试 ReAct Agent Tool Calling Loop 的 Fake 客户端
    可模拟:
    1. 单次工具调用后输出文本
    2. 死循环工具调用 (测试 max_steps 门禁)
    3. 直接流式输出文本
    """
    def __init__(self, behavior: str = "infinite_tools"):
        self.behavior = behavior
        self.call_count = 0

    class Chat:
        def __init__(self, outer):
            self.outer = outer

        class Completions:
            def __init__(self, outer):
                self.outer = outer

            async def create(self, model: str, messages: List[Dict[str, Any]], tools: Any = None, temperature: float = 0.3, stream: bool = True):
                self.outer.call_count += 1
                count = self.outer.call_count

                if self.outer.behavior == "infinite_tools":
                    # 永远返回 tool_call，促使 runner 达到 max_steps 强制终止
                    async def infinite_gen():
                        yield FakeChunk(tool_calls=[
                            FakeToolCall(f"call_{count}", "search_policy_kb", '{"query": "保修"}')
                        ])
                    return infinite_gen()

                elif self.outer.behavior == "single_tool_then_text":
                    if count == 1:
                        async def tool_gen():
                            yield FakeChunk(tool_calls=[
                                FakeToolCall("call_1", "compare_products", '{"spu_codes": ["HP-VICTUS-16", "HP-OMEN-16-SLIM"]}')
                            ])
                        return tool_gen()
                    else:
                        async def text_gen():
                            for ch in "对比完成：光影精灵16重2.3kg，暗影精灵16 Slim重2.1kg，差价2000元。":
                                yield FakeChunk(content=ch)
                        return text_gen()

                else:
                    async def default_gen():
                        for ch in "这是直接回复的文本":
                            yield FakeChunk(content=ch)
                    return default_gen()

        @property
        def completions(self):
            return self.Completions(self.outer)

    @property
    def chat(self):
        return self.Chat(self)

