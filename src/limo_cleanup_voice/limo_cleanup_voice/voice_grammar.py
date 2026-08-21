# Copyright 2026 DYH
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Bottle-only experiment grammar retained for reproducible offline A/B.

This list is not the recommended runtime default: real-WAV evidence regressed
from unrestricted exact 2/4, CER 0.357143 to exact 1/4, CER 1.142857.  The
intent-level ``瓶子`` alias remains valid independently of this ASR result.
"""


DEFAULT_GRAMMAR = [
    '小莫 小莫 开始 清理',
    '小莫 小莫 捡 塑料瓶',
    '小莫 小莫 捡 瓶子',
    '小莫 小莫 处理 瓶子',
    '小莫 小莫 识别 瓶子',
    '小莫 小莫 捡 易拉罐',
    '小莫 小莫 捡 纸盒',
    '小莫 小莫 捡 垃圾',
    '小莫 小莫 碰 一下 塑料瓶',
    '小莫 小莫 报告 状态',
    '小莫 小莫 到 垃圾桶 旁边 去',
    '确认', '取消', '停下', '停止 任务', '紧急 停止', '[unk]',
]
