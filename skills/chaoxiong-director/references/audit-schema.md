# 结构化生产核销

`scripts/audit_production.py` 是Python标准库工具。输入JSON及可选完整提示词文本，成功exit=0，错误exit=1。E/F操作不使用视频manifest，按其操作记录检查；本工具覆盖A/B/C/D视频规划，不处理像素或实际语音。

## JSON字段

schema_version=1；delivery_scope=complete或partial。

platform：max_duration正数；evidence当前入口/资料来源；native_cuts布尔值；cuts_evidence切镜能力证据；supported_controls列表。文档证据不冒称实际测试，缺失具体能力时先保守规划，勿为通过脚本伪造证据。

source_dialogue：每项id、order整数、speaker、text原文。dialogue_ledger：每项同id和status=Executed/Carried/Authorized；Carried有destination且仅partial合法；Authorized有authorization；Executed必须有完整audio_segments。

source_parameters：每项id、category、value。parameter_ledger：同id、status、carrier执行承载；结转/授权要求与DIA一致。十二类适用PID先由导演完整建立，脚本只能检查给定集合覆盖，不能证明来源集合没有漏列。

groups：按剪辑顺序列id、route（A/B/C/A/C/B/D）、duration与shots。每个shot有全球唯一id、start/end（G内剪辑时间）、完整start_state/end_state物理字典。前后字典应连续；时间跳跃、换场、回忆、蒙太奇或原资料支持的边界变化填写boundary.kind/reason/source_ref。CAM变化不放入物理状态；同镜中移动写到end_state。脚本只核验边界声明，不判断原文是否真能支持。

calls：id、group_id、shot_ids、generation_duration、edit_in/edit_out（素材裁剪时间）、start_kind=independent、reference_ids。B/C-B每S一CALL；A/C-A/D每G一CALL；D仅一S；素材裁剪时长等于对应剪辑时长。参考references每项id、role、binding真实引用、accessible；尾帧另记kind=tail_frame、source_group/source_call，跨组禁止，B独立CALL也禁止相互尾帧依赖。

audio_segments：dia_id、shot_id、char_start/char_end（Python Unicode字符索引，含标点）、text原文切片、speaker、audio_owner、lip_sync_owner（画外为null）、on_screen、start/end（G内音频时间）、track、master_track。字位连续、不重复、不漏字，按母时间轴保持DIA原顺序。同轨不能重叠；原剧情允许同步对白时采用独立轨道。跨剪辑切点声音合法，只要范围在G内且正确拥有者；跨G声音在各G切片并共享母轨。

同DIA分多个镜头的切片必须最终覆盖整句；分批可在完整DIA边界交付，若必须中句暂停，先保存具体字位游标，不把半句标为完全Executed。

## 提示词文本

每个CALL对应一个START/END块，每块依次十四标题，第一字段全局核心要求，不允许空字段、同上或未填模板。脚本不自动证明正文与JSON一致，提交前仍需逐卡交叉核对身份、人数、持物、DIA文字与时间。

## 校验范围

检查ID重复、台词总账覆盖/归属/字符片段/顺序、合法授权和结转、时间空缺重叠、路由调用数、控制能力声明、素材裁剪、参考绑定、独立起手、状态边界与字段顺序。报告media_verified恒为false。不得把通过结果写成实际电影质量、空间像素或口型已经通过。
