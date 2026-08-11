import json
import os
import re
import threading
import urllib.error
import urllib.request

import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String


CANONICAL_COMMANDS = {
    'plastic_bottle': '捡塑料瓶',
    'can': '捡易拉罐',
    'paper_box': '捡纸盒',
    'generic_waste': '捡垃圾',
}
TOUCH_CANONICAL_COMMAND = '触碰矿泉水瓶'

LOCAL_KEYWORDS = {
    'plastic_bottle': ('塑料瓶', '矿泉水瓶', '饮料瓶', 'plastic bottle', 'bottle'),
    'can': ('易拉罐', '罐子', 'can'),
    'paper_box': ('纸盒', '纸箱', '纸板', 'carton', 'paper box'),
    'generic_waste': ('垃圾', '废物', 'trash', 'garbage', 'waste'),
}

STOP_KEYWORDS = ('停止', '取消', '终止', 'stop', 'cancel', 'abort')
TOUCH_KEYWORDS = ('触碰', '碰一下', '轻触', '接触', 'touch', 'tap')

SYSTEM_PROMPT = """You convert a user's cleanup-robot instruction into JSON.
Return JSON only, without Markdown.
Allowed actions: pick_and_dispose, touch_only, stop, unsupported.
Allowed object_class values: plastic_bottle, can, paper_box,
generic_waste, null.
Schema: {"action":"...","object_class":"... or null","reason":"..."}.
Never invent an object category. A request to stop or cancel has action stop.
touch_only is allowed only for plastic_bottle and means one pre-touch,
light-touch, retreat sequence without a gripper.
"""


class LanguageUnderstandingNode(Node):
    def __init__(self) -> None:
        super().__init__('cleanup_language_understanding')

        status_qos = QoSProfile(depth=10)
        status_qos.reliability = ReliabilityPolicy.RELIABLE
        status_qos.durability = DurabilityPolicy.TRANSIENT_LOCAL

        self.command_publisher = self.create_publisher(
            String, '/cleanup/command_text', 10)
        self.status_publisher = self.create_publisher(
            String, '/cleanup/language_status', status_qos)
        self.create_subscription(
            String, '/cleanup/natural_language', self.text_callback, 10)

        self.base_url = os.getenv(
            'LIMO_LLM_BASE_URL',
            os.getenv('OPENAI_BASE_URL', 'http://192.168.1.123:8317/v1'),
        ).rstrip('/')
        self.api_key = os.getenv(
            'LIMO_LLM_API_KEY', os.getenv('OPENAI_API_KEY', '')).strip()
        self.model = os.getenv('LIMO_LLM_MODEL', '').strip()
        self.request_timeout = float(os.getenv('LIMO_LLM_TIMEOUT', '20'))
        self.request_lock = threading.Lock()

        mode = 'llm' if self.api_key and self.model else 'local_fallback'
        self.publish_status(mode, 'Language node is ready')
        self.get_logger().info(
            f'Ready on /cleanup/natural_language; mode={mode}')

    def text_callback(self, message: String) -> None:
        raw_text = message.data.strip()
        if not raw_text:
            self.publish_status('rejected', 'Input text is empty')
            return

        if not self.request_lock.acquire(blocking=False):
            self.publish_status('busy', 'A language request is already running')
            return

        worker = threading.Thread(
            target=self.process_text,
            args=(raw_text,),
            daemon=True,
        )
        worker.start()

    def process_text(self, raw_text: str) -> None:
        try:
            if self.api_key and self.model:
                try:
                    intent = self.request_llm(raw_text)
                    source = 'llm'
                except Exception as error:  # noqa: BLE001
                    self.get_logger().warning(
                        f'LLM request failed; using local fallback: {error}')
                    intent = self.parse_locally(raw_text)
                    source = 'local_fallback_after_error'
            else:
                intent = self.parse_locally(raw_text)
                source = 'local_fallback'

            command = self.intent_to_command(intent, raw_text)
            self.publish_command(command)
            self.publish_status(
                'published',
                f'Published normalized command using {source}',
                intent=intent,
            )
        except ValueError as error:
            self.publish_status('rejected', str(error))
        finally:
            self.request_lock.release()

    def request_llm(self, raw_text: str) -> dict:
        payload = {
            'model': self.model,
            'temperature': 0,
            'messages': [
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': raw_text},
            ],
        }
        request = urllib.request.Request(
            f'{self.base_url}/chat/completions',
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {self.api_key}',
                'Content-Type': 'application/json',
            },
            method='POST',
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=self.request_timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as error:
            body = error.read(300).decode('utf-8', errors='replace')
            raise RuntimeError(f'HTTP {error.code}: {body}') from error

        content = result['choices'][0]['message']['content']
        return self.extract_json(content)

    @staticmethod
    def extract_json(content: str) -> dict:
        cleaned = content.strip()
        cleaned = re.sub(r'^```(?:json)?\s*', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\s*```$', '', cleaned)
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start < 0 or end < start:
            raise ValueError('The language model did not return a JSON object')
        parsed = json.loads(cleaned[start:end + 1])
        if not isinstance(parsed, dict):
            raise ValueError('The language model result is not a JSON object')
        return parsed

    @staticmethod
    def parse_locally(raw_text: str) -> dict:
        text = raw_text.lower()
        if any(keyword in text for keyword in STOP_KEYWORDS):
            return {'action': 'stop', 'object_class': None, 'reason': 'stop keyword'}

        object_class = None
        for object_class, keywords in LOCAL_KEYWORDS.items():
            if any(keyword in text for keyword in keywords):
                break
        else:
            object_class = None

        if any(keyword in text for keyword in TOUCH_KEYWORDS):
            if object_class == 'plastic_bottle':
                return {
                    'action': 'touch_only',
                    'object_class': object_class,
                    'reason': 'local touch keyword match',
                }
            return {
                'action': 'unsupported',
                'object_class': object_class,
                'reason': 'touch_only supports plastic_bottle only',
            }

        if object_class is not None:
            return {
                'action': 'pick_and_dispose',
                'object_class': object_class,
                'reason': 'local object keyword match',
            }

        return {
            'action': 'unsupported',
            'object_class': None,
            'reason': 'no supported object class',
        }

    @staticmethod
    def intent_to_command(intent: dict, raw_text: str) -> str:
        action = intent.get('action')
        object_class = intent.get('object_class')

        if action == 'stop':
            return '停止任务'
        if action == 'pick_and_dispose' and object_class in CANONICAL_COMMANDS:
            return CANONICAL_COMMANDS[object_class]
        if action == 'touch_only' and object_class == 'plastic_bottle':
            return TOUCH_CANONICAL_COMMAND
        if action == 'unsupported':
            return raw_text
        raise ValueError('The parsed instruction is not supported or is incomplete')

    def publish_command(self, command: str) -> None:
        message = String()
        message.data = command
        self.command_publisher.publish(message)
        self.get_logger().info(f'Published normalized command: {command}')

    def publish_status(self, state: str, detail: str, intent=None) -> None:
        payload = {'state': state, 'detail': detail}
        if intent is not None:
            payload['intent'] = intent
        message = String()
        message.data = json.dumps(payload, ensure_ascii=False)
        self.status_publisher.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = LanguageUnderstandingNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
