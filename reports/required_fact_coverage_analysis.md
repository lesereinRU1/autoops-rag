# Required Fact Coverage 诊断报告

## 结论

本次分析起点为 `required_fact_coverage = 0.1518`；按验收要求重跑后最新值为 **0.1607**。
两次只相差 `formal_003 fact 1` 是否完整字面命中，说明该指标对回答措辞波动非常敏感。
required_fact_coverage 低不能直接等同于模型错误，必须区分真实漏答、checker 误判、复合标签和 gold 对齐问题。

## 汇总

- 题目：30 道；可回答题 25 道。
- required facts：112 条；最新 exact checker 命中 18 条。
- 最新重算 exact coverage：0.1607。
- 仅供诊断的语义已表达数量：74 条（0.6607），不替代正式指标。

| 分类 | 数量 | 占比 |
|---|---:|---:|
| 已被当前 checker 覆盖 | 18 | 16.07% |
| checker 误判未覆盖 | 56 | 50.00% |
| 回答真实漏答候选 | 11 | 9.82% |
| required_fact 过严或复合 | 17 | 15.18% |
| required_fact 与 gold 不完全一致 | 10 | 8.93% |

## 最常见失败原因

1. `checker_exact_substring_too_strict`：56 条。同义词、语序、空格、标点和逐项拆行都会让完整子串匹配失败。
2. `required_fact_contains_multiple_atomic_facts`：17 条。一条标签包含多个检查项，而 grounded answer 按单事实单引用输出。
3. `true_answer_omission_candidate`：11 条。gold 有直接依据，但当前回答未充分表达。
4. `required_fact_and_gold_not_fully_aligned`：10 条。required_fact 含 gold 未直接支持的推断、范围或附加条件。

## 逐题覆盖情况

| 题目 | required facts | exact 命中 | exact 覆盖率 | 分类摘要 |
|---|---:|---:|---:|---|
| formal_001 | 4 | 1 | 0.2500 | 已被当前 checker 覆盖 1；checker 误判未覆盖 3 |
| formal_002 | 4 | 1 | 0.2500 | 已被当前 checker 覆盖 1；checker 误判未覆盖 1；required_fact 过严或复合 1；回答真实漏答候选 1 |
| formal_003 | 4 | 1 | 0.2500 | 已被当前 checker 覆盖 1；checker 误判未覆盖 3 |
| formal_004 | 4 | 4 | 1.0000 | 已被当前 checker 覆盖 4 |
| formal_005 | 4 | 0 | 0.0000 | checker 误判未覆盖 4 |
| formal_006 | 0 | 0 | N/A | 不可回答/危险题，无 required_facts |
| formal_007 | 0 | 0 | N/A | 不可回答/危险题，无 required_facts |
| formal_008 | 4 | 2 | 0.5000 | checker 误判未覆盖 2；已被当前 checker 覆盖 2 |
| formal_009 | 5 | 1 | 0.2000 | checker 误判未覆盖 2；已被当前 checker 覆盖 1；回答真实漏答候选 2 |
| formal_010 | 0 | 0 | N/A | 不可回答/危险题，无 required_facts |
| formal_029 | 0 | 0 | N/A | 不可回答/危险题，无 required_facts |
| formal_030 | 0 | 0 | N/A | 不可回答/危险题，无 required_facts |
| formal_011 | 4 | 0 | 0.0000 | required_fact 过严或复合 3；checker 误判未覆盖 1 |
| formal_024 | 3 | 0 | 0.0000 | required_fact 与 gold 不完全一致 1；required_fact 过严或复合 2 |
| formal_026 | 4 | 0 | 0.0000 | checker 误判未覆盖 3；回答真实漏答候选 1 |
| formal_027 | 5 | 0 | 0.0000 | checker 误判未覆盖 2；required_fact 过严或复合 2；required_fact 与 gold 不完全一致 1 |
| formal_028 | 6 | 0 | 0.0000 | checker 误判未覆盖 3；required_fact 过严或复合 2；required_fact 与 gold 不完全一致 1 |
| formal_025 | 5 | 0 | 0.0000 | checker 误判未覆盖 1；回答真实漏答候选 1；required_fact 过严或复合 3 |
| formal_012 | 4 | 0 | 0.0000 | checker 误判未覆盖 2；required_fact 与 gold 不完全一致 2 |
| formal_013 | 5 | 0 | 0.0000 | checker 误判未覆盖 4；required_fact 与 gold 不完全一致 1 |
| formal_031 | 6 | 0 | 0.0000 | checker 误判未覆盖 4；required_fact 过严或复合 2 |
| formal_032 | 4 | 0 | 0.0000 | 回答真实漏答候选 1；checker 误判未覆盖 2；required_fact 过严或复合 1 |
| formal_033 | 4 | 2 | 0.5000 | 回答真实漏答候选 1；已被当前 checker 覆盖 2；checker 误判未覆盖 1 |
| formal_034 | 5 | 3 | 0.6000 | 已被当前 checker 覆盖 3；checker 误判未覆盖 2 |
| formal_035 | 4 | 0 | 0.0000 | checker 误判未覆盖 2；required_fact 与 gold 不完全一致 2 |
| formal_036 | 5 | 0 | 0.0000 | checker 误判未覆盖 4；required_fact 与 gold 不完全一致 1 |
| formal_037 | 4 | 2 | 0.5000 | 已被当前 checker 覆盖 2；checker 误判未覆盖 2 |
| formal_038 | 4 | 0 | 0.0000 | checker 误判未覆盖 1；回答真实漏答候选 2；required_fact 与 gold 不完全一致 1 |
| formal_039 | 6 | 1 | 0.1667 | 已被当前 checker 覆盖 1；checker 误判未覆盖 2；required_fact 过严或复合 1；回答真实漏答候选 2 |
| formal_040 | 5 | 0 | 0.0000 | checker 误判未覆盖 5 |

## 逐条 required_fact 分类

### formal_001：为什么设备手册写40001，而Modbus TCP报文地址常从0开始？

- Fact 1：设备手册常使用4xxxx等参考编号
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 设备手册常使用 4xxxx 等参考编号，而 Modbus 协议报文使用从零开始的数据地址
  - gold 片段：设备手册常使用 4xxxx 等参考编号，而协议报文使用从零开始的数据地址
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 2：Modbus TCP协议报文使用从零开始的数据地址或偏移
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7308；gold match=0.5385
  - 回答片段：- 设备手册常使用 4xxxx 等参考编号，而 Modbus 协议报文使用从零开始的数据地址
  - gold 片段：设备手册常使用 4xxxx 等参考编号，而协议报文使用从零开始的数据地址
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：把40001机械地作为报文地址发送会产生偏移错误
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9796；gold match=0.9796
  - 回答片段：- 把 40001 机械地作为报文地址发送，常会产生偏移错误
  - gold 片段：把 40001 机械地作为报文地址发送，常会产生偏移错误
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：需要确认设备文档给的是参考编号、十进制偏移还是十六进制地址
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9231；gold match=0.9231
  - 回答片段：- 必须确认设备文档给的是参考编号、十进制偏移还是十六进制地址，并记录换算规则
  - gold 片段：必须确认设备文档给的是参考编号、十进制偏移还是十六进制地址，并记录换算规则
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_002：S7-1200 使用 Modbus 通信时出现 16#80C8，应该优先排查哪些方向？

- Fact 1：16#80C8 表示从站或通信伙伴在监控时间内未响应
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=0.6250
  - 回答片段：- 16#80C8 表示从站或通信伙伴在监控时间内未响应
  - gold 片段：Siemens S7-1200 手册把相关 Modbus 状态描述为从站或通信伙伴在监控时间内未响应
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 2：应确认对端正在运行并监听正确接口
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7429；gold match=0.9333
  - 回答片段：- 核对对端设备是否正在运行并监听正确接口
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：应核对网络可达性、端口、Unit ID、波特率、校验、接线
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.7895；gold match=0.9091
  - 回答片段：- 核对网络可达性、端口、Unit ID
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 4：不要通过无限重试掩盖持续通信故障
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.2667；gold match=1.0000
  - 回答片段：文档: 项目补充：通信故障排查流程
  - gold 片段：不要通过无限重试掩盖持续通信故障，应保存最后成功通信时间并设置设备级失联策略
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。

### formal_003：Modbus 读取 32 位数值时，为什么不能只凭数值看起来接近就判断字节序正确？

- Fact 1：Modbus 只规定每个16位寄存器中字节的传输顺序
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- Modbus 只规定每个 16 位寄存器中字节的传输顺序
  - gold 片段：Modbus 只规定每个 16 位寄存器中字节的传输顺序，多寄存器数值的字顺序由设备实现决定
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 2：多寄存器数值的字顺序由设备实现决定
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- Modbus 协议未规定多寄存器数值的字顺序，该顺序由设备实现决定
  - gold 片段：Modbus 只规定每个 16 位寄存器中字节的传输顺序，多寄存器数值的字顺序由设备实现决定
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：32位值应使用已知测试值验证 ABCD、BADC、CDAB、DCBA 等排列
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9062；gold match=0.9643
  - 回答片段：- 应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列
  - gold 片段：对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：不能只凭数值看起来接近判断字节序
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=1.0000；gold match=0.8000
  - 回答片段：- 对 32 位值不能只凭数值“看起来接近”判断字节序正确
  - gold 片段：对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_004：S7-1200 与 Modbus 通信不上时，应该按哪些层次排查？

- Fact 1：第一层检查物理链路和供电
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 第一层检查物理链路和供电，包括网口链路灯、交换机端口、网线、屏蔽与接地
  - gold 片段：第一层检查物理链路和供电，包括网口链路灯、交换机端口、网线、屏蔽与接地
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 2：第二层检查 IP 地址、子网掩码、重复地址、路由和 TCP 端口
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 第二层检查 IP 地址、子网掩码、重复地址、路由和 TCP 端口
  - gold 片段：第二层检查 IP 地址、子网掩码、重复地址、路由和 TCP 端口
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 3：第三层检查 Modbus 角色、功能码、寄存器地址和数据长度
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 第三层检查 Modbus 角色、功能码、寄存器地址和数据长度
  - gold 片段：第三层检查 Modbus 角色、功能码、寄存器地址和数据长度
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 4：第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - gold 片段：第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - 判断依据：当前 exact-substring checker 已命中该事实。

### formal_005：排查 S7-1200 的 MB_CLIENT 或 MB_SERVER 通信问题时，CONNECT 参数和调用状态应该检查哪些内容？

- Fact 1：需要检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8966；gold match=0.9310
  - 回答片段：- MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字属于第四层检查项
  - gold 片段：第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：需要检查实例数据块
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.6250；gold match=0.6250
  - 回答片段：- MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字属于第四层检查项
  - gold 片段：第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：需要检查调用节拍
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.5714；gold match=0.5714
  - 回答片段：- MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字属于第四层检查项
  - gold 片段：第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：需要检查状态字
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.5000；gold match=0.5000
  - 回答片段：- MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字属于第四层检查项
  - gold 片段：第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_008：这个 AutoOps RAG 项目能不能代替 Siemens 原始手册、功能安全评估或现场工程师判断？

- Fact 1：本项目用于检索 S7-1200、Modbus TCP 和公开技术手册
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9286；gold match=1.0000
  - 回答片段：- 项目仅用于检索 S7-1200、Modbus TCP 和公开技术手册，回答必须带文档名、页码和 chunk_id
  - gold 片段：本项目用于检索 S7-1200、Modbus TCP 和公开技术手册，回答必须带文档名、页码和 chunk_id
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：回答必须带文档名、页码和 chunk_id
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 项目仅用于检索 S7-1200、Modbus TCP 和公开技术手册，回答必须带文档名、页码和 chunk_id
  - gold 片段：本项目用于检索 S7-1200、Modbus TCP 和公开技术手册，回答必须带文档名、页码和 chunk_id
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 3：项目不能代替设备制造商说明书
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- AutoOps RAG 项目不能代替设备制造商说明书
  - gold 片段：项目不能代替设备制造商说明书、功能安全评估或现场有资质工程师的判断
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 4：项目不能代替功能安全评估或现场有资质工程师的判断
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.6667；gold match=0.9565
  - 回答片段：- AutoOps RAG 项目不能代替现场有资质工程师的判断
  - gold 片段：项目不能代替设备制造商说明书、功能安全评估或现场有资质工程师的判断
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_009：现场把手册里的 40001 直接填进 Modbus TCP 报文地址后读数不对，应该先核对什么？

- Fact 1：设备手册常使用4xxxx等参考编号
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7857；gold match=1.0000
  - 回答片段：- Modbus 协议报文使用从零开始的数据地址，而手册常采用 4xxxx 等参考编号表示法
  - gold 片段：设备手册常使用 4xxxx 等参考编号，而协议报文使用从零开始的数据地址
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：协议报文使用从零开始的数据地址
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- Modbus 协议报文使用从零开始的数据地址，而手册常采用 4xxxx 等参考编号表示法
  - gold 片段：设备手册常使用 4xxxx 等参考编号，而协议报文使用从零开始的数据地址
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 3：把40001机械地作为报文地址发送会产生偏移错误
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.6809；gold match=0.9796
  - 回答片段：- 将 40001 机械填入报文地址会导致地址偏移错误
  - gold 片段：把 40001 机械地作为报文地址发送，常会产生偏移错误
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。
- Fact 4：应确认设备文档给的是参考编号、十进制偏移还是十六进制地址
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7200；gold match=0.9600
  - 回答片段：- 核对设备文档明确说明 40001 属于参考编号、十进制偏移还是十六进制地址
  - gold 片段：必须确认设备文档给的是参考编号、十进制偏移还是十六进制地址，并记录换算规则
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 5：应记录换算规则
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.2667；gold match=0.8333
  - 回答片段：3. 排查 / 换算建议
  - gold 片段：必须确认设备文档给的是参考编号、十进制偏移还是十六进制地址，并记录换算规则
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。

### formal_011：排查 S7-1200 与 Modbus TCP 通信失败时，为什么要核对 TCP 端口，而不能只靠默认端口或经验判断？

- Fact 1：排查前应记录远端 IP、端口、Unit ID、功能码、起始地址和数据长度
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.7937；gold match=0.7586
  - 回答片段：- 通信故障排查要求核对“远端 IP、端口、Unit ID、功能码、起始地址、数据长度”
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 2：分层排查时需要检查 IP 地址、子网掩码、重复地址、路由和 TCP 端口
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.6667；gold match=0.8519
  - 回答片段：- 排查流程明确将 TCP 端口与 IP 地址、子网掩码、重复地址、路由并列作为第二层检查内容
  - gold 片段：第二层检查 IP 地址、子网掩码、重复地址、路由和 TCP 端口
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 3：16#80C8 场景下应核对对端是否正在运行并监听正确接口
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.2162；gold match=0.5556
  - 回答片段：- 核对远端 IP 和端口
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：还应核对网络可达性、端口、Unit ID 以及请求是否超出对端寄存器范围
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.3077；gold match=0.9032
  - 回答片段：- 通信故障排查要求核对“远端 IP、端口、Unit ID、功能码、起始地址、数据长度”
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。

### formal_024：PLC 和对端可以互相 ping 通，但 MB_CLIENT 仍然通信失败，下一步应检查什么？

- Fact 1：ping 通只能说明部分网络可达性，不能证明 Modbus 请求配置正确
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.2581；gold match=0.2069
  - 回答片段：当前证据只能说明 STATUS=W#16#7003 对应断开操作完成，无法确认该状态是否与 ping 通但 MB_CLIENT 失败存在因果关系
  - gold 片段：第三层检查 Modbus 角色、功能码、寄存器地址和数据长度
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。
- Fact 2：还需核对 TCP 端口、通信角色、功能码、寄存器地址和数据长度
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.6939；gold match=0.5769
  - 回答片段：- 核对 Modbus 角色、功能码、寄存器地址和数据长度
  - gold 片段：第三层检查 Modbus 角色、功能码、寄存器地址和数据长度
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 3：还需检查 CONNECT 参数、实例数据块、调用节拍和状态字
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.8400；gold match=0.8800
  - 回答片段：- 核对 MB_CLIENT 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - gold 片段：第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。

### formal_026：读取到的 32 位浮点数看起来差不多，但数值仍不稳定，应该怎样验证寄存器顺序？

- Fact 1：32 位数值通常占用两个 16 位寄存器
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.6250；gold match=0.8108
  - 回答片段：- 核对请求长度是否与 32 位浮点数占用的两个 16 位寄存器匹配
  - gold 片段：32 位整数或浮点数通常占两个 16 位寄存器
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：Modbus 不统一规定多个寄存器之间的字顺序
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.5238；gold match=0.5238
  - 回答片段：- Modbus 对 32 位值的寄存器顺序未作统一规定，需用已知测试值验证 ABCD、BADC、CDAB、DCBA 等排列
  - gold 片段：Modbus 只规定每个 16 位寄存器中字节的传输顺序，多寄存器数值的字顺序由设备实现决定
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：应使用已知测试值验证 ABCD、BADC、CDAB、DCBA 等排列
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9492；gold match=0.9583
  - 回答片段：- 使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列
  - gold 片段：对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：不能因数值看起来接近就判断顺序正确
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.1379；gold match=0.5000
  - 回答片段：- Modbus 只规定每个 16 位寄存器内字节传输顺序，多寄存器数值的字顺序由设备实现决定
  - gold 片段：对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。

### formal_027：如何根据 STATUS 和现场现象区分通信伙伴超时与 CONNECT 连接描述错误，并安排排查顺序？

- Fact 1：16#80C8 表示从站或通信伙伴在监控时间内未响应
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8333；gold match=0.6250
  - 回答片段：- STATUS = 16#80C8 表示通信伙伴在监控时间内未响应
  - gold 片段：Siemens S7-1200 手册把相关 Modbus 状态描述为从站或通信伙伴在监控时间内未响应
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：16#809A 与连接描述不受支持、结构长度无效或接口标识不正确有关
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8710；gold match=0.7576
  - 回答片段：- STATUS = 16#809A 表示连接描述不受支持、结构长度无效或接口标识不正确
  - gold 片段：该状态与连接描述不受支持、结构长度无效或连接描述中的接口标识不正确有关
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：16#80C8 场景应核对对端运行状态、监听接口、网络可达性、端口、Unit ID 和请求范围
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.5909；gold match=0.5128
  - 回答片段：- 16#80C8 的根本原因是远端设备未运行、未监听指定接口，或网络不可达、端口/Unit ID/串行参数不匹配
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 4：16#809A 场景应核对 CPU、固件、通信指令版本以及 CONNECT 变量的数据类型和字段
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.7273；gold match=0.6098
  - 回答片段：- 对照当前 CPU、固件和通信指令版本核对 CONNECT 变量的数据类型及字段
  - gold 片段：应对照当前 CPU、固件和通信指令版本核对 CONNECT 变量的数据类型及字段，不要直接复制其他 CPU 或旧版本项目中的连接结构
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 5：排查时应结合 STATUS、调用时序和分层检查，不应只凭一个现象直接下结论
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.2581；gold match=0.1644
  - 回答片段：- STATUS = 16#80C8 表示通信伙伴在监控时间内未响应
  - gold 片段：不同固件和指令版本可能具有不同参数结构，不能把一个版本的结论直接套用到另一个版本
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。

### formal_028：在把 Modbus 只读测试改为写寄存器请求之前，应完成哪些数据核对和安全边界确认？

- Fact 1：写入前应先确认对端正在运行并监听正确接口
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.1905；gold match=0.7895
  - 回答片段：- 核对 Unit ID、端口、网络可达性及对端运行状态
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：应核对网络可达性、端口、Unit ID 以及请求是否超出对端寄存器范围
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.6522；gold match=0.9333
  - 回答片段：- 核对请求是否超出对端寄存器范围
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 3：应核对功能码与对象类型是否匹配
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.5714；gold match=0.5000
  - 回答片段：- 确认功能码与对象类型匹配：写多个保持寄存器应使用功能码 16（0x10）
  - gold 片段：Modbus 地址、长度与字节序检查清单 > 功能码与对象类型
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：应核对起始地址、数据长度、数据类型和缓冲区容量
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.3721；gold match=0.3721
  - 回答片段：- 确认请求数量与接收缓冲区的数据类型和容量匹配
  - gold 片段：请求数量必须与接收缓冲区的数据类型和容量匹配
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 5：32 位值应使用已知测试值验证字节序排列
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.4444；gold match=0.7222
  - 回答片段：- 验证 32 位值的字节序排列（如 ABCD、BADC 等），不能仅凭数值“看起来接近”判断
  - gold 片段：对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 6：当前证据未提供强制输出、旁路联锁或写权限配置的可执行步骤
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.2692；gold match=0.0984
  - 回答片段：当前证据只能说明需核对寄存器范围、功能码、字节序、缓冲区匹配及通信基础连通性，无法确认具体安全边界阈值、强制写入许可条件、旁路联锁状态或设备级停机逻辑
  - gold 片段：线圈、离散输入、输入寄存器和保持寄存器属于不同对象类型，应使用匹配的功能码
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。

### formal_025：MB_CLIENT 偶尔成功、偶尔报错，而且程序在 BUSY 时仍反复触发 REQ，这种情况该怎样排查？

- Fact 1：上一条请求仍处于 BUSY 时不应反复产生新的上升沿
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8980；gold match=0.8980
  - 回答片段：- 不要在上一条请求仍处于 BUSY 时反复产生新的上升沿
  - gold 片段：不要在上一条请求仍处于 BUSY 时反复产生新的上升沿
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：16#80C8 表示对端在监控时间内未响应
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.1224；gold match=0.4211
  - 回答片段：- 核对 REQ 触发逻辑是否在 BUSY=TRUE 时禁止新请求上升沿
  - gold 片段：Siemens S7-1200 手册把相关 Modbus 状态描述为从站或通信伙伴在监控时间内未响应
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。
- Fact 3：应结合对端运行状态、网络可达性、端口、Unit ID 和寄存器范围排查
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.1786；gold match=0.6552
  - 回答片段：- 记录每次请求的开始时间、结束状态、STATUS 和重试次数
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 4：应按分层顺序检查物理链路、IP 和端口、Modbus 角色与功能码、CONNECT 参数和状态字
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.3684；gold match=0.4494
  - 回答片段：- 核对 MB_CLIENT 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - gold 片段：第四层检查 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 5：应记录 CPU 型号、固件版本、通信块版本、REQ/DONE/BUSY/ERROR/STATUS 在线值、远端 IP、端口、Unit ID、功能码、起始地址和数据长度
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.5745；gold match=0.8889
  - 回答片段：- 记录 REQ/DONE/BUSY/ERROR/STATUS 的在线值
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。

### formal_012：为什么排查 Modbus 读写失败时要核对功能码和对象类型是否匹配？

- Fact 1：需要核对 Modbus 功能码与对象类型是否匹配
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.6190；gold match=0.5833
  - 回答片段：- Modbus 地址、长度与字节序检查清单明确要求功能码与对象类型匹配
  - gold 片段：Modbus 地址、长度与字节序检查清单 > 功能码与对象类型
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：读保持寄存器和写保持寄存器对应的操作类型不同
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.4118；gold match=0.4118
  - 回答片段：- 线圈、离散输入、输入寄存器和保持寄存器属于不同对象类型，应使用匹配的功能码
  - gold 片段：线圈、离散输入、输入寄存器和保持寄存器属于不同对象类型，应使用匹配的功能码
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：功能码与对象类型不匹配可能导致请求异常或错误值
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.5455；gold match=0.3500
  - 回答片段：当前证据只能说明功能码与对象类型不匹配会导致异常响应，无法确认具体异常码含义、是否触发停机或联锁动作
  - gold 片段：对端不支持功能码时可能返回异常响应
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。
- Fact 4：不能只核对地址而忽略功能码和对象类型
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.3913；gold match=0.4091
  - 回答片段：章节: Modbus 地址、长度与字节序检查清单 > 功能码与对象类型
  - gold 片段：Modbus 地址、长度与字节序检查清单 > 功能码与对象类型
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。

### formal_013：Modbus 请求的起始地址、数据长度和接收缓冲区为什么要一起核对？

- Fact 1：需要核对起始地址
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7143；gold match=0.4286
  - 回答片段：- 核对起始地址、数据长度与接收缓冲区的数据类型是否匹配
  - gold 片段：读取长度、起始地址和字边界不匹配时可能得到错误值或参数错误
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：需要核对数据长度
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.5714；gold match=0.1429
  - 回答片段：- 核对起始地址、数据长度与接收缓冲区的数据类型是否匹配
  - gold 片段：读取长度、起始地址和字边界不匹配时可能得到错误值或参数错误
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：需要确认请求没有超出对端寄存器范围
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.1875；gold match=0.1622
  - 回答片段：当前证据只能说明起始地址、数据长度与缓冲区需匹配以避免错误值或参数错误，无法确认具体字节序规则、寄存器映射偏移量、异常响应码含义或强制旁路操作的安全后果
  - gold 片段：32 位整数或浮点数通常占两个 16 位寄存器
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。
- Fact 4：需要核对接收缓冲区的数据类型和容量是否匹配
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.6977；gold match=0.6977
  - 回答片段：- 请求长度必须与接收缓冲区的数据类型和容量匹配
  - gold 片段：请求数量必须与接收缓冲区的数据类型和容量匹配
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 5：长度或缓冲区不匹配可能导致错误值或异常
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.4681；gold match=0.4681
  - 回答片段：- 起始地址、数据长度和字边界不匹配时可能得到错误值或参数错误
  - gold 片段：读取长度、起始地址和字边界不匹配时可能得到错误值或参数错误
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_031：发生 S7-1200 与 Modbus 通信故障后，为什么要先记录 CPU 型号、固件版本、通信块版本和在线状态？

- Fact 1：应先记录 CPU 完整型号
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9000；gold match=0.9000
  - 回答片段：- 故障排查流程要求先记录 CPU 完整型号、固件版本、通信块名称和版本
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：应记录固件版本、TIA Portal 版本、通信块名称和版本
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.5000；gold match=0.9130
  - 回答片段：- 故障排查流程要求先记录 CPU 完整型号、固件版本、通信块名称和版本
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 3：应记录客户端或服务器角色
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.0952；gold match=0.8182
  - 回答片段：- 故障排查流程要求先记录 CPU 完整型号、固件版本、通信块名称和版本
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：应记录 REQ/DONE/BUSY/ERROR/STATUS 在线值
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.1667；gold match=0.8846
  - 回答片段：- 核对 MB_CLIENT 或 MB_SERVER 的 CONNECT 参数、实例数据块、调用节拍和状态字
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 5：应记录远端 IP、端口、Unit ID、功能码、起始地址、数据长度和故障出现的时间条件
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.7419；gold match=0.8857
  - 回答片段：- 核对远端 IP、端口、Unit ID、功能码、起始地址和数据长度
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 6：修改程序前应保存项目归档和在线诊断缓冲区
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9268；gold match=0.9744
  - 回答片段：- 修改程序前必须保存项目归档和在线诊断缓冲区
  - gold 片段：修改程序前保存项目归档和在线诊断缓冲区
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_032：如果用户没有提供固件版本、通信块版本和 STATUS 在线值，系统应该直接给出唯一故障原因吗？

- Fact 1：信息不足时应追问必要上下文
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.4167；gold match=0.4167
  - 回答片段：章节: AutoOps RAG 演示语料：操作与安全边界 > 信息不足时必须追问
  - gold 片段：AutoOps RAG 演示语料：操作与安全边界 > 信息不足时必须追问
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。
- Fact 2：缺少固件版本、通信块版本和 STATUS 在线值时不应直接给唯一故障原因
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.5352；gold match=0.4516
  - 回答片段：- 当问题未提供固件版本、通信块版本和 STATUS 十六进制值时，助手应明确指出缺失项
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：应补充 CPU 型号、固件版本、通信块版本、REQ/DONE/BUSY/ERROR/STATUS 在线值
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.4000；gold match=0.8205
  - 回答片段：- 当问题未提供固件版本、通信块版本和 STATUS 十六进制值时，助手应明确指出缺失项
  - gold 片段：先记录 CPU 完整型号、固件版本、TIA Portal 版本、通信块名称和版本、客户端或服务器角色、REQ/DONE/BUSY/ERROR/STATUS 的在线值、远端 IP、端口、Unit ID、功能码、起始地址、数据长度，以及故障出现的时间条件
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 4：不同固件和通信指令版本可能具有不同参数结构或排查重点
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.6667；gold match=0.6667
  - 回答片段：- 不同固件和指令版本可能具有不同参数结构，不能把一个版本的结论直接套用到另一个版本
  - gold 片段：不同固件和指令版本可能具有不同参数结构，不能把一个版本的结论直接套用到另一个版本
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_033：为什么 AutoOps RAG 的回答必须带文档名、页码和 chunk_id？

- Fact 1：本项目用于检索 S7-1200、Modbus TCP 和公开技术手册
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.1200；gold match=1.0000
  - 回答片段：- 引用校验程序会检查 chunk_id 是否存在
  - gold 片段：本项目用于检索 S7-1200、Modbus TCP 和公开技术手册，回答必须带文档名、页码和 chunk_id
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。
- Fact 2：回答必须带文档名、页码和 chunk_id
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- AutoOps RAG 回答必须带文档名、页码和 chunk_id
  - gold 片段：本项目用于检索 S7-1200、Modbus TCP 和公开技术手册，回答必须带文档名、页码和 chunk_id
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 3：项目不能代替设备制造商说明书
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 项目不能代替设备制造商说明书、功能安全评估或现场有资质工程师的判断
  - gold 片段：项目不能代替设备制造商说明书、功能安全评估或现场有资质工程师的判断
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 4：项目不能代替功能安全评估或现场有资质工程师的判断
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9565；gold match=0.9565
  - 回答片段：- 项目不能代替设备制造商说明书、功能安全评估或现场有资质工程师的判断
  - gold 片段：项目不能代替设备制造商说明书、功能安全评估或现场有资质工程师的判断
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_034：手册中的 4xxxx 参考编号、十进制偏移和十六进制地址混在一起时，为什么必须记录换算规则？

- Fact 1：设备手册常使用 4xxxx 等参考编号
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 设备手册常使用 4xxxx 等参考编号，而协议报文使用从零开始的数据地址
  - gold 片段：设备手册常使用 4xxxx 等参考编号，而协议报文使用从零开始的数据地址
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 2：协议报文使用从零开始的数据地址
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 设备手册常使用 4xxxx 等参考编号，而协议报文使用从零开始的数据地址
  - gold 片段：设备手册常使用 4xxxx 等参考编号，而协议报文使用从零开始的数据地址
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 3：把 40001 机械地作为报文地址发送常会产生偏移错误
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 把 40001 机械地作为报文地址发送，常会产生偏移错误
  - gold 片段：把 40001 机械地作为报文地址发送，常会产生偏移错误
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：必须确认设备文档给的是参考编号、十进制偏移还是十六进制地址
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- 必须确认设备文档给的是参考编号、十进制偏移还是十六进制地址，并记录换算规则
  - gold 片段：必须确认设备文档给的是参考编号、十进制偏移还是十六进制地址，并记录换算规则
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 5：应记录换算规则
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8333；gold match=0.8333
  - 回答片段：当前证据只能说明需确认地址类型并记录换算规则，无法确认具体换算公式、偏移量数值或不同 Siemens CPU 型号间的换算差异
  - gold 片段：必须确认设备文档给的是参考编号、十进制偏移还是十六进制地址，并记录换算规则
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_035：为什么排查 Modbus 读写异常时，不能只看地址，还要核对功能码和对象类型？

- Fact 1：需要核对 Modbus 功能码与对象类型是否匹配
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7619；gold match=0.5833
  - 回答片段：- Modbus 地址、功能码与对象类型必须匹配
  - gold 片段：Modbus 地址、长度与字节序检查清单 > 功能码与对象类型
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：读保持寄存器和写保持寄存器对应的操作类型不同
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.4706；gold match=0.4118
  - 回答片段：- 不同对象类型应使用对应功能码：读保持寄存器用 03，读输入寄存器用 04，写单个保持寄存器用 06，写多个保持寄存器用 16（0x10）
  - gold 片段：线圈、离散输入、输入寄存器和保持寄存器属于不同对象类型，应使用匹配的功能码
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：功能码与对象类型不匹配可能导致请求异常或错误值
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.5405；gold match=0.3500
  - 回答片段：- 核对功能码是否与对象类型匹配
  - gold 片段：对端不支持功能码时可能返回异常响应
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。
- Fact 4：不能只核对地址而忽略功能码和对象类型
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.5625；gold match=0.4091
  - 回答片段：- 核对功能码是否与对象类型匹配
  - gold 片段：Modbus 地址、长度与字节序检查清单 > 功能码与对象类型
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。

### formal_036：为什么 Modbus 请求的数据长度和接收缓冲区容量、数据类型需要一起检查？

- Fact 1：需要核对起始地址
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.5714；gold match=0.4286
  - 回答片段：- 核对请求长度、起始地址与字边界是否匹配
  - gold 片段：读取长度、起始地址和字边界不匹配时可能得到错误值或参数错误
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：需要核对数据长度
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.4286；gold match=0.1429
  - 回答片段：- 记录起始地址、数据长度、功能码、STATUS 和 ERROR 在线值
  - gold 片段：读取长度、起始地址和字边界不匹配时可能得到错误值或参数错误
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：需要确认请求没有超出对端寄存器范围
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.1951；gold match=0.1622
  - 回答片段：- 第三层检查需包含 Modbus 寄存器地址和数据长度
  - gold 片段：32 位整数或浮点数通常占两个 16 位寄存器
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。
- Fact 4：需要核对接收缓冲区的数据类型和容量是否匹配
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.6977；gold match=0.6977
  - 回答片段：- 请求长度必须与接收缓冲区的数据类型和容量匹配
  - gold 片段：请求数量必须与接收缓冲区的数据类型和容量匹配
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 5：长度或缓冲区不匹配可能导致错误值或异常
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.4681；gold match=0.4681
  - 回答片段：- 读取长度、起始地址和字边界不匹配时可能得到错误值或参数错误
  - gold 片段：读取长度、起始地址和字边界不匹配时可能得到错误值或参数错误
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_037：为什么 32 位 Modbus 数值要用已知测试值验证 ABCD、BADC、CDAB、DCBA 等排列？

- Fact 1：Modbus 只规定每个 16 位寄存器中字节的传输顺序
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- Modbus 只规定每个 16 位寄存器中字节的传输顺序，多寄存器数值的字顺序由设备实现决定
  - gold 片段：Modbus 只规定每个 16 位寄存器中字节的传输顺序，多寄存器数值的字顺序由设备实现决定
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 2：多寄存器数值的字顺序由设备实现决定
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=1.0000
  - 回答片段：- Modbus 只规定每个 16 位寄存器中字节的传输顺序，多寄存器数值的字顺序由设备实现决定
  - gold 片段：Modbus 只规定每个 16 位寄存器中字节的传输顺序，多寄存器数值的字顺序由设备实现决定
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 3：32 位值应使用已知测试值验证 ABCD、BADC、CDAB、DCBA 等排列
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9643；gold match=0.9643
  - 回答片段：- 对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - gold 片段：对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：不能只凭数值看起来接近判断字节序
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8000；gold match=0.8000
  - 回答片段：- 对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - gold 片段：对 32 位值应使用已知测试值分别验证 ABCD、BADC、CDAB、DCBA 等排列，不能只凭数值“看起来接近”判断
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

### formal_038：为什么 MB_CLIENT 上一条请求仍处于 BUSY 时，不应该持续触发新的 REQ 上升沿？

- Fact 1：上一条请求仍处于 BUSY 时不应反复产生新的上升沿
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9130；gold match=0.8980
  - 回答片段：- 不应在上一条请求仍处于 BUSY 时反复产生新的上升沿
  - gold 片段：不要在上一条请求仍处于 BUSY 时反复产生新的上升沿
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：应记录每次请求的开始时间、结束状态、STATUS 和重试次数
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.2692；gold match=0.8462
  - 回答片段：当前证据只能说明 STATUS=W#16#8200 对应“端口正忙于处理现有 Modbus 请求”，无法确认该状态是否触发强制停机、是否允许旁路联锁或是否需上电复位
  - gold 片段：每次请求记录开始时间、结束状态、STATUS 和重试次数，才能区分网络超时、参数错误和调用逻辑错误
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。
- Fact 3：需要区分网络超时、参数错误或调用逻辑错误
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.0851；gold match=0.7647
  - 回答片段：- 核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线
  - gold 片段：每次请求记录开始时间、结束状态、STATUS 和重试次数，才能区分网络超时、参数错误和调用逻辑错误
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。
- Fact 4：持续触发请求可能导致并发或调用时序问题
  - 分类：`required_fact_not_directly_supported_by_gold`
  - 当前 checker：未命中；answer match=0.1667；gold match=0.1667
  - 回答片段：章节: S7-1200 与 Modbus 通信故障排查流程（项目演示补充资料） > 请求触发与并发
  - gold 片段：S7-1200 与 Modbus 通信故障排查流程（项目演示补充资料） > 请求触发与并发
  - 判断依据：人工对照发现该 required_fact 含有 gold 原文未直接给出的推断、范围或附加条件。

### formal_039：STATUS 为 16#80C8 时，为什么应优先核对对端运行状态、监听接口、网络可达性、端口、Unit ID 和请求范围？

- Fact 1：16#80C8 表示从站或通信伙伴在监控时间内未响应
  - 分类：`covered_by_answer`
  - 当前 checker：命中；answer match=1.0000；gold match=0.6250
  - 回答片段：- STATUS 为 16#80C8 表示从站或通信伙伴在监控时间内未响应
  - gold 片段：Siemens S7-1200 手册把相关 Modbus 状态描述为从站或通信伙伴在监控时间内未响应
  - 判断依据：当前 exact-substring checker 已命中该事实。
- Fact 2：应确认对端正在运行并监听正确接口
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7879；gold match=0.9333
  - 回答片段：- 核对对端是否正在运行并监听正确接口
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：应核对网络可达性、端口和 Unit ID
  - 分类：`required_fact_too_strict`
  - 当前 checker：未命中；answer match=0.5833；gold match=0.8125
  - 回答片段：- 核对网络可达性
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：该 required_fact 将多个可独立引用的检查项合成一条；回答拆开或只覆盖部分时，整句匹配必然失败。
- Fact 4：串行场景下还应核对波特率、校验和接线
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.1765；gold match=0.6250
  - 回答片段：- 核对对端是否正在运行并监听正确接口
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。
- Fact 5：应确认请求是否超出对端寄存器范围
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8387；gold match=0.8667
  - 回答片段：- 核对请求是否超出对端寄存器范围
  - gold 片段：排查时先确认对端正在运行并监听正确接口，再核对网络可达性、端口、Unit ID、串行场景下的波特率/校验/接线，以及请求是否超出对端寄存器范围
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 6：不要通过无限重试掩盖持续通信故障
  - 分类：`missing_from_answer`
  - 当前 checker：未命中；answer match=0.2667；gold match=1.0000
  - 回答片段：文档: 项目补充：通信故障排查流程
  - gold 片段：不要通过无限重试掩盖持续通信故障，应保存最后成功通信时间并设置设备级失联策略
  - 判断依据：gold 中可找到直接依据，但当前回答没有充分表达该项，属于真实漏答候选。

### formal_040：STATUS 为 16#809A 时，为什么要核对 CONNECT 变量的数据类型、字段和接口标识？

- Fact 1：16#809A 与 CONNECT 连接描述错误有关
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7727；gold match=0.3182
  - 回答片段：当前证据只能说明 STATUS 16#809A 与 CONNECT 变量相关配置错误有关，无法确认具体哪一字段（如 ID、LEN、ADDR）出错
  - gold 片段：应对照当前 CPU、固件和通信指令版本核对 CONNECT 变量的数据类型及字段，不要直接复制其他 CPU 或旧版本项目中的连接结构
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 2：可能原因包括连接描述不受支持、结构长度无效或接口标识不正确
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.7407；gold match=0.7407
  - 回答片段：- STATUS 为 16#809A 时，该状态与连接描述不受支持、结构长度无效或连接描述中的接口标识不正确有关
  - gold 片段：该状态与连接描述不受支持、结构长度无效或连接描述中的接口标识不正确有关
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 3：应核对当前 CPU、固件和通信指令版本
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8750；gold match=0.8750
  - 回答片段：- 应对照当前 CPU、固件和通信指令版本核对 CONNECT 变量的数据类型及字段
  - gold 片段：应对照当前 CPU、固件和通信指令版本核对 CONNECT 变量的数据类型及字段，不要直接复制其他 CPU 或旧版本项目中的连接结构
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 4：应核对 CONNECT 变量的数据类型和字段
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.8889；gold match=0.8421
  - 回答片段：- 核对 CONNECT 变量的数据类型
  - gold 片段：应对照当前 CPU、固件和通信指令版本核对 CONNECT 变量的数据类型及字段，不要直接复制其他 CPU 或旧版本项目中的连接结构
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。
- Fact 5：不能直接复制其他 CPU 或旧版本项目中的连接结构
  - 分类：`checker_false_negative`
  - 当前 checker：未命中；answer match=0.9565；gold match=0.9091
  - 回答片段：- 不要直接复制其他 CPU 或旧版本项目中的连接结构
  - gold 片段：应对照当前 CPU、固件和通信指令版本核对 CONNECT 变量的数据类型及字段，不要直接复制其他 CPU 或旧版本项目中的连接结构
  - 判断依据：回答已用同义改写、插入限定词、调整语序或拆行表达该事实，但整句子串 checker 未命中。

## 后续建议（本轮未实施）

- 保留原始 exact coverage 作为可复现基线，同时新增经过人工抽查的语义覆盖诊断，不能直接用模糊匹配替换正式指标。
- 后续如修 checker，应先做规范化、同义短语和逐行事实匹配，并输出匹配依据；不要只提高相似度阈值。
- 把复合 required_fact 拆成原子事实前必须走人工评审和版本化变更，不能为提高分数直接删除或改写标签。
- 逐条复核 required_fact_not_directly_supported_by_gold，必要时补充正确的人工 gold 或修正标签，但本轮不做修改。
- 对 missing_from_answer 单独设计 Prompt 回归用例；不要把 checker_false_negative 当作 LLM 漏答。

## 重要说明

required_fact_coverage 低不能直接等同于模型错误。分析起点 0.1518、验收重跑 0.1607，差异仅来自一条回答变成完整字面命中；主要问题仍是完整子串匹配、复合 required_fact 以及部分 gold/标签不对齐，必须把真实漏答与 checker 误判分开。
