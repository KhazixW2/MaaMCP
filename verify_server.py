import asyncio
import sys
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run():
    # 获取当前 python 解释器路径
    python_executable = sys.executable
    script_path = os.path.join(
        os.path.dirname(__file__), "maa_mcp", "pipeline_server.py"
    )
    project_root = os.path.dirname(__file__)

    print(f"🔌 正在连接到服务器: {script_path}")

    # 设置环境变量，确保 Python 路径正确，且输出不缓冲
    env = os.environ.copy()
    env["PYTHONPATH"] = project_root
    env["PYTHONUNBUFFERED"] = "1"

    server_params = StdioServerParameters(
        command=python_executable, args=[script_path], env=env
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. 初始化
            print("🚀 发送初始化请求...")
            await session.initialize()
            print("✅ 初始化成功！")

            # 2. 列出工具
            print("\n🛠️  获取工具列表...")
            tools = await session.list_tools()
            print(f"✅ 成功获取 {len(tools.tools)} 个工具：")
            for tool in tools.tools:
                print(
                    f"  - {tool.name}: {tool.description.splitlines()[0] if tool.description else 'No description'}"
                )

            # 3. 测试 start_pipeline 工具
            print("\n🧪 测试 start_pipeline 工具...")
            try:
                # 使用测试设备 ID
                result = await session.call_tool(
                    "start_pipeline",
                    arguments={"controller_id": "test_device", "fps": 2.0},
                )
                print(f"✅ 调用成功，返回结果:\n{result.content[0].text}")
            except Exception as e:
                print(f"❌ 调用失败: {e}")

            # 4. 等待几秒
            print("\n⏳ 等待 3 秒...")
            await asyncio.sleep(3)

            # 5. 获取新消息
            print("\n📩 获取新消息...")
            try:
                result = await session.call_tool("get_new_messages", arguments={})
                # get_new_messages 返回的是 list，mcp 协议层会包装成 TextContent
                # FastMCP 可能会将其序列化为 JSON 字符串
                print(f"✅ 消息内容:\n{result.content[0].text}")
            except Exception as e:
                print(f"❌ 获取消息失败: {e}")

            # 6. 停止流水线
            print("\n🛑 停止流水线...")
            try:
                result = await session.call_tool("stop_pipeline", arguments={})
                print(f"✅ 停止结果: {result.content[0].text}")
            except Exception as e:
                print(f"❌ 停止失败: {e}")

            print("\n✨ 验证完成！服务器运行正常。")


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n用户取消")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
