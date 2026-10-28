# -*- coding: utf-8 -*-
"""拼音归一（lib 层）：移植自站点客户端 `site/build.py` 的 `_pinyin_tokens` 口径。

背景
----
站点客户端的拼音层（`app.js` 的 `pinyinFetch()` / `layerCandidates()`）依赖构建产物
`data/idx/pinyin.json`（token → 索引条目），lib/search.py 之前没有对应能力，导致
CLI/tests/服务端检索无法命中拼音查询（reports/search-eval-v3.md 的 65 例 gap）。

本模块把同一套 **默认读音字表 + token 口径**（s:音节 / j:连写 / i:首字母）移植进 lib，
并在 lib 侧额外提供 **多音字候选**（`POLYPHONE_EXTRA`）——客户端行为不变：
  - 字表来源：`site/build.py::_PINYIN_CHARS_TEXT`（1,582 字，生成时快照，见文件底部），
    `python .tmp/pinyin-lib/gen_pinyin_lib.py` 可重新提取；
  - token 生成与客户端 `_pinyin_tokens()` 完全一致（polyphone=False 时）；
  - 本模块只在 lib/CLI/tests 侧使用，**不进入站点 dist**，不增加页面体积；
  - 客户端仍用构建的 pinyin.json（默认读音），多音字候选是 lib 的超集能力。

许可：字表本身是 pinyin-pro（MIT）生成的读音数据，构建侧已在用；读音/药名属事实数据。
"""
from __future__ import annotations

import re

# 汉字 → 默认拼音（与 site/build.py 的 _PINYIN_CHARS_TEXT 同源）
_PINYIN_CHARS_TEXT = """䓬:zhuo 一:yi 丁:ding 七:qi 万:wan 三:san 上:shang 下:xia 不:bu 与:yu 专:zhuan 世:shi 丙:bing 业:ye 东:dong 丝:si
两:liang 严:yan 中:zhong 丰:feng 临:lin 丸:wan 丹:dan 为:wei 丽:li 乃:nai 久:jiu 之:zhi 乌:wu 乎:hu 乐:le 乙:yi
九:jiu 乱:luan 乳:ru 了:liao 予:yu 二:er 云:yun 五:wu 亚:ya 亢:kang 交:jiao 亦:yi 产:chan 京:jing 亭:ting 亮:liang
人:ren 亿:yi 仁:ren 今:jin 介:jie 仑:lun 仔:zai 仕:shi 他:ta 仙:xian 仟:qian 代:dai 令:ling 仪:yi 仲:zhong 价:jia
任:ren 伉:kang 伊:yi 伏:fu 伐:fa 休:xiu 众:zhong 优:you 伞:san 伟:wei 伤:shang 伦:lun 伪:wei 伯:bo 伲:ni 伴:ban
伶:ling 伸:shen 伽:jia 位:wei 低:di 佐:zuo 佑:you 体:ti 佛:fo 佩:pei 佰:bai 佳:jia 佶:ji 使:shi 侗:dong 供:gong 依:yi
侣:lü 侬:nong 便:bian 促:cu 俊:jun 保:bao 信:xin 俪:li 修:xiu 倍:bei 倡:chang 倩:qian 假:jia 停:ting 健:jian 催:cui
傲:ao 僖:xi 儒:ru 儿:er 允:yun 元:yuan 充:chong 兆:zhao 先:xian 光:guang 克:ke 免:mian 兔:tu 入:ru 全:quan 八:ba
公:gong 六:liu 兮:xi 兰:lan 关:guan 兴:xing 兵:bing 其:qi 典:dian 兹:zi 养:yang 内:nei 冉:ran 册:ce 再:zai 军:jun
农:nong 冠:guan 冬:dong 冰:bing 冲:chong 决:jue 冷:leng 冻:dong 净:jing 凌:ling 减:jian 凝:ning 凡:fan 凯:kai
出:chu 分:fen 切:qie 列:lie 则:ze 刚:gang 创:chuang 初:chu 利:li 别:bie 制:zhi 刹:cha 刺:ci 刻:ke 剂:ji 前:qian
剑:jian 力:li 功:gong 加:jia 动:dong 助:zhu 努:nu 劲:jin 劳:lao 勃:bo 勉:mian 勒:le 勤:qin 包:bao 化:hua 北:bei
匙:chi 匹:pi 区:qu 十:shi 千:qian 升:sheng 卉:hui 半:ban 华:hua 协:xie 卓:zhuo 单:dan 南:nan 博:bo 卜:bu 卟:bu
占:zhan 卡:ka 卢:lu 卤:lu 卫:wei 即:ji 卵:luan 卷:juan 厄:e 历:li 压:ya 原:yuan 去:qu 参:can 及:ji 友:you 双:shuang
反:fan 发:fa 叔:shu 取:qu 受:shou 变:bian 口:kou 古:gu 只:zhi 叮:ding 可:ke 台:tai 史:shi 右:you 叶:ye 号:hao 司:si
合:he 吉:ji 同:tong 名:ming 后:hou 吐:tu 吖:a 吗:ma 君:jun 吡:bi 吨:dun 吩:fen 含:han 启:qi 吲:yin 吸:xi 吻:wen 吾:wu
呋:fu 呗:bai 呤:ling 呫:tie 呱:gua 味:wei 呵:he 呼:hu 命:ming 咀:zui 和:he 咐:fu 咖:ka 咛:ning 咨:zi 咪:mi 咯:ge
咳:hai 品:pin 哈:ha 哌:pai 哒:da 哚:duo 哥:ge 哲:zhe 唐:tang 唑:zuo 唛:mai 唯:wei 唾:tuo 商:shang 啉:lin 啡:fei
啶:ding 喃:nan 善:shan 喉:hou 喏:nuo 喜:xi 喷:pen 喹:kui 嗉:su 嗜:shi 嗪:qin 嘉:jia 嘌:piao 嘧:mi 嘿:hei 噁:e 器:qi
噬:shi 噻:sai 嚼:jiao 囊:nang 囗:wei 四:si 因:yin 固:gu 国:guo 图:tu 土:tu 圣:sheng 在:zai 地:di 均:jun 坎:kan
坏:huai 坤:kun 坦:tan 垂:chui 型:xing 埃:ai 域:yu 培:pei 基:ji 堂:tang 塔:ta 塞:sai 增:zeng 墩:dun 壁:bi 士:shi
壬:ren 壮:zhuang 声:sheng 壹:yi 备:bei 复:fu 夏:xia 外:wai 多:duo 夜:ye 大:da 天:tian 太:tai 夫:fu 失:shi 头:tou
夷:yi 夸:kua 奇:qi 奈:nai 奉:feng 奋:fen 奎:kui 奕:yi 奥:ao 女:nü 奴:nu 好:hao 如:ru 妇:fu 妈:ma 妙:miao 妤:yu 妥:tuo
妮:ni 姆:mu 姜:jiang 威:wei 娜:na 婕:jie 婷:ting 媒:mei 子:zi 孕:yun 存:cun 孚:fu 孛:bei 孟:meng 孢:bao 学:xue 孩:hai
宁:ning 它:ta 宇:yu 安:an 宏:hong 宓:mi 宗:zong 定:ding 宜:yi 宝:bao 实:shi 宣:xuan 宫:gong 家:jia 容:rong 宾:bin
密:mi 富:fu 寒:han 对:dui 导:dao 封:feng 射:she 将:jiang 小:xiao 尓:er 尔:er 尖:jian 尘:chen 尚:shang 尤:you 尼:ni
尽:jin 尿:niao 层:ceng 屈:qu 屋:wu 屏:ping 屑:xie 山:shan 岁:sui 岚:lan 岛:dao 岩:yan 峰:feng 崩:beng 川:chuan
工:gong 左:zuo 巧:qiao 巨:ju 巯:qiu 己:ji 已:yi 巴:ba 布:bu 帅:shuai 帆:fan 希:xi 帕:pa 帝:di 带:dai 帮:bang 常:chang
幔:man 干:gan 平:ping 幸:xing 广:guang 庆:qing 库:ku 应:ying 庚:geng 度:du 康:kang 延:yan 廷:ting 廸:di 建:jian
廿:nian 开:kai 异:yi 式:shi 弗:fu 弘:hong 张:zhang 弥:mi 弹:tan 强:qiang 归:gui 当:dang 彤:tong 影:ying 彼:bi
征:zheng 待:dai 律:lü 得:de 御:yu 循:xun 微:wei 德:de 心:xin 必:bi 忆:yi 志:zhi 快:kuai 念:nian 忻:xin 忾:kai 思:si
怡:yi 性:xing 总:zong 恒:heng 恤:xu 恩:en 恪:ke 恬:tian 息:xi 恺:kai 悉:xi 悦:yue 悬:xuan 惟:wei 惠:hui 愈:yu 意:yi
感:gan 慢:man 慧:hui 慰:wei 慷:kang 戈:ge 戊:wu 成:cheng 戴:dai 扁:bian 手:shou 扎:zha 扑:pu 托:tuo 扬:yang 扰:rao
扶:fu 承:cheng 抑:yi 抒:shu 抗:kang 折:zhe 抚:fu 护:hu 拉:la 拓:tuo 拜:bai 择:ze 拿:na 挺:ting 换:huan 捷:jie 接:jie
控:kong 提:ti 握:wo 援:yuan 搏:bo 搽:cha 撒:sa 擎:qing 支:zhi 收:shou 攸:you 改:gai 放:fang 效:xiao 敌:di 敏:min
敖:ao 敢:gan 散:san 敦:dun 敬:jing 整:zheng 敷:fu 文:wen 斑:ban 断:duan 斯:si 新:xin 方:fang 施:shi 旁:pang 旋:xuan
无:wu 日:ri 旦:dan 旨:zhi 旭:xu 时:shi 旺:wang 昂:ang 昆:kun 昊:hao 昌:chang 明:ming 易:yi 昔:xi 昕:xin 昙:tan
星:xing 春:chun 显:xian 晋:jin 晓:xiao 晗:han 晟:sheng 晨:chen 普:pu 景:jing 晴:qing 晶:jing 智:zhi 暴:bao 曲:qu
更:geng 曼:man 曾:ceng 替:ti 月:yue 朋:peng 服:fu 朗:lang 望:wang 期:qi 朦:meng 木:mu 末:mo 本:ben 术:shu 朴:pu
朵:duo 机:ji 杆:gan 杉:shan 李:li 杏:xing 杖:zhang 杜:du 束:shu 来:lai 杨:yang 杭:hang 杰:jie 杷:pa 松:song 板:ban
极:ji 构:gou 枇:pi 析:xi 林:lin 果:guo 枝:zhi 枢:shu 枯:ku 架:jia 枸:gou 柏:bai 柑:gan 柔:rou 柠:ning 柯:ke 柳:liu
柴:chai 树:shu 栓:shuan 栢:bai 株:zhu 样:yang 核:he 根:gen 格:ge 桂:gui 桃:tao 桉:an 桑:sang 桔:ju 桦:hua 梅:mei
梗:geng 梨:li 梭:suo 检:jian 棉:mian 棒:bang 棓:bang 棕:zong 棘:ji 森:sen 植:zhi 椒:jiao 榄:lan 榈:lü 榔:lang
榕:rong 榭:xie 榴:liu 槐:huai 槟:bin 樟:zhang 橘:ju 橙:cheng 橼:yuan 檗:bo 檬:meng 次:ci 欢:huan 欣:xin 欧:ou 歌:ge
止:zhi 正:zheng 步:bu 武:wu 歧:qi 死:si 殊:shu 殷:yin 毅:yi 母:mu 每:mei 毒:du 毓:yu 比:bi 毕:bi 毛:mao 氏:shi 民:min
气:qi 氘:dao 氟:fu 氢:qing 氧:yang 氨:an 氮:dan 氯:lü 氰:qing 水:shui 永:yong 汀:ting 汁:zhi 汇:hui 汉:han 汕:shan
汝:ru 汞:gong 汰:tai 沁:qin 沂:yi 沃:wo 沐:mu 沙:sha 沛:pei 没:mei 沥:li 沫:mo 河:he 油:you 治:zhi 泉:quan 泊:bo 泌:mi
法:fa 泛:fan 泡:pao 波:bo 注:zhu 泪:lei 泮:pan 泯:min 泰:tai 泻:xie 泼:po 泽:ze 洁:jie 洋:yang 洗:xi 洛:luo 津:jin
洲:zhou 活:huo 派:pai 流:liu 浆:jiang 测:ce 济:ji 浓:nong 浙:zhe 浦:pu 浩:hao 浪:lang 海:hai 浸:jin 涂:tu 消:xiao
涓:juan 润:run 液:ye 涵:han 淀:dian 淑:shu 深:shen 淳:chun 混:hun 添:tian 清:qing 渗:shen 渠:qu 温:wen 渭:wei
港:gang 游:you 湖:hu 溉:gai 源:yuan 溢:yi 溴:xiu 溶:rong 滋:zi 滔:tao 滞:zhi 满:man 滤:lü 滨:bin 滴:di 漱:shu 潇:xiao
潘:pan 澜:lan 澳:ao 激:ji 瀚:han 灌:guan 火:huo 灭:mie 灰:hui 灵:ling 炉:lu 炎:yan 炔:que 炭:tan 点:dian 烃:ting
烟:yan 热:re 烯:xi 烷:wan 焦:jiao 然:ran 熊:xiong 熙:xi 熹:xi 爱:ai 爽:shuang 片:pian 牙:ya 牛:niu 牡:mu 物:wu 特:te
犀:xi 犬:quan 状:zhuang 狂:kuang 狄:di 狗:gou 独:du 猗:yi 猛:meng 猪:zhu 猫:mao 猴:hou 玄:xuan 玉:yu 王:wang 玖:jiu
玛:ma 玥:yue 玫:mei 环:huan 玻:bo 珀:po 珂:ke 珊:shan 珍:zhen 珐:fa 珑:long 珞:luo 珠:zhu 班:ban 珮:pei 球:qiu
琅:lang 理:li 琥:hu 琦:qi 琪:qi 琳:lin 琴:qin 琼:qiong 瑙:nao 瑚:hu 瑜:yu 瑞:rui 瑟:se 璃:li 璐:lu 璞:pu 瓜:gua 瓦:wa
甘:gan 甜:tian 生:sheng 用:yong 甫:fu 田:tian 由:you 甲:jia 申:shen 电:dian 甾:zai 畅:chang 留:liu 番:fan 疏:shu
疗:liao 疫:yi 疮:chuang 疱:pao 疹:zhen 病:bing 症:zheng 痔:zhi 痘:dou 痛:tong 痢:li 瘤:liu 癌:ai 癣:xuan 癸:gui
登:deng 白:bai 百:bai 皂:zao 的:de 皆:jie 皇:huang 皓:hao 皮:pi 皿:min 盈:ying 益:yi 盐:yan 盒:he 盖:gai 盘:pan
盛:sheng 盟:meng 目:mu 直:zhi 相:xiang 盼:pan 盾:dun 眉:mei 真:zhen 眩:xuan 眼:yan 睦:mu 睾:gao 睿:rui 矛:mao 知:zhi
短:duan 石:shi 矾:fan 砂:sha 研:yan 砜:feng 破:po 砷:shen 础:chu 硅:gui 硒:xi 硝:xiao 硫:liu 硬:ying 确:que 硼:peng
碇:ding 碘:dian 碧:bi 碱:jian 碳:tan 磊:lei 磷:lin 磺:huang 示:shi 社:she 祛:qu 祝:zhu 神:shen 祥:xiang 祺:qi 禄:lu
福:fu 离:li 禾:he 秀:xiu 秋:qiu 种:zhong 科:ke 秘:mi 秦:qin 积:ji 移:yi 稀:xi 稳:wen 穆:mu 穗:sui 穿:chuan 立:li
童:tong 端:duan 竹:zhu 笋:sun 笑:xiao 笔:bi 笛:di 符:fu 策:ce 简:jian 算:suan 管:guan 米:mi 类:lei 籽:zi 粉:fen 粒:li
粘:nian 粟:su 精:jing 糊:hu 糖:tang 糜:mi 糠:kang 系:xi 素:su 索:suo 紧:jin 紫:zi 累:lei 红:hong 纤:xian 纬:wei
纯:chun 纱:sha 纳:na 纷:fen 纽:niu 纾:shu 线:xian 组:zu 绅:shen 细:xi 织:zhi 绍:shao 经:jing 绒:rong 结:jie 给:gei
绛:jiang 络:luo 统:tong 绣:xiu 绥:sui 绪:xu 绮:qi 维:wei 绵:mian 综:zong 绿:lü 缇:ti 缌:si 缓:huan 缘:yuan 缩:suo
缬:xie 缺:que 罂:ying 罗:luo 置:zhi 羊:yang 美:mei 羔:gao 羚:ling 羟:qiang 群:qun 羧:suo 羽:yu 翁:weng 翔:xiang
翘:qiao 翰:han 考:kao 而:er 耐:nai 耳:er 联:lian 聚:ju 聪:cong 肉:rou 肌:ji 肖:xiao 肝:gan 肟:wo 肠:chang 肤:fu
肥:fei 肪:fang 肯:ken 育:yu 肺:fei 肼:jing 肽:tai 肾:shen 肿:zhong 胀:zhang 胂:shen 胃:wei 胆:dan 胍:gua 胎:tai
胚:pei 胜:sheng 胞:bao 胡:hu 胭:yan 胰:yi 胱:guang 胶:jiao 胸:xiong 胺:an 能:neng 脂:zhi 脉:mai 脊:ji 脑:nao 脒:mi
脯:pu 脱:tuo 脲:niao 脾:pi 腈:jing 腐:fu 腔:qiang 腙:zong 腥:xing 腮:sai 腹:fu 腺:xian 腾:teng 膏:gao 膜:mo 膦:lin
膨:peng 臣:chen 自:zi 至:zhi 致:zhi 臻:zhen 臼:jiu 舌:she 舍:she 舒:shu 良:liang 色:se 艾:ai 节:jie 芊:qian 芍:shao
芎:xiong 芙:fu 芝:zhi 芥:jie 芦:lu 芩:qin 芪:qi 芬:fen 芭:ba 芮:rui 芯:xin 花:hua 芳:fang 芷:zhi 芸:yun 芽:ya 苄:bian
苏:su 苓:ling 苗:miao 若:ruo 苦:ku 苧:zhu 苯:ben 英:ying 苷:gan 苹:ping 茁:zhuo 茄:qie 茉:mo 茚:yin 茛:gen 茜:qian
茴:hui 茵:yin 茶:cha 荃:quan 荆:jing 草:cao 荟:hui 荣:rong 荧:ying 药:yao 荷:he 荻:di 莎:sha 莨:lang 莪:e 莫:mo
莰:kan 莱:lai 莲:lian 获:huo 莹:ying 菁:jing 菇:gu 菊:ju 菌:jun 菏:he 菖:chang 菜:cai 菠:bo 菪:dang 菱:ling 菲:fei
萄:tao 萌:meng 萘:nai 萝:luo 营:ying 萨:sa 萩:qiu 落:luo 葆:bao 葎:lü 葛:ge 葡:pu 葵:kui 蒂:di 蒎:pai 蒙:meng 蒜:suan
蒲:pu 蒽:en 蒿:hao 蓉:rong 蓓:bei 蓝:lan 蓟:ji 蓣:yu 蔓:man 蔗:zhe 蔺:lin 蔻:kou 蕊:rui 蕲:qi 薁:yu 薄:bao 薇:wei
薯:shu 藤:teng 藻:zao 虎:hu 虑:lü 虫:chong 虹:hong 蚓:yin 蛇:she 蛋:dan 蛎:li 蛙:wa 蛹:yong 蜂:feng 蜚:fei 蜜:mi
蜡:la 蝎:xie 蝥:mao 蝮:fu 蝶:die 融:rong 螨:man 螺:luo 蠊:lian 血:xue 行:xing 衍:yan 衡:heng 衣:yi 补:bu 表:biao
袋:dai 裂:lie 装:zhuang 裕:yu 西:xi 见:jian 观:guan 视:shi 角:jiao 解:jie 言:yan 誉:yu 讯:xun 记:ji 设:she 诊:zhen
试:shi 诗:shi 诚:cheng 诺:nuo 谊:yi 谓:wei 谛:di 谱:pu 谷:gu 豆:dou 象:xiang 豪:hao 贝:bei 贞:zhen 质:zhi 贯:guan
贴:tie 贵:gui 费:fei 贺:he 贻:yi 赋:fu 赐:ci 赖:lai 赛:sai 赞:zan 赤:chi 赫:he 超:chao 越:yue 跃:yue 路:lu 踪:zong
蹄:ti 身:shen 车:che 轩:xuan 转:zhuan 轮:lun 软:ruan 轻:qing 载:zai 较:jiao 辅:fu 辉:hui 输:shu 辛:xin 辣:la 辰:chen
辽:liao 达:da 迁:qian 迅:xun 过:guo 迈:mai 运:yun 近:jin 返:fan 还:hai 远:yuan 连:lian 迦:jia 迪:di 迭:die 迷:mi
适:shi 选:xuan 逊:xun 透:tou 通:tong 速:su 造:zao 逸:yi 逻:luo 遇:yu 道:dao 那:na 邦:bang 邻:lin 郁:yu 郝:hao 都:dou
酊:ding 配:pei 酐:gan 酒:jiu 酚:fen 酞:tai 酪:lao 酮:tong 酯:zhi 酰:xian 酵:jiao 酶:mei 酸:suan 酿:niang 醇:chun
醋:cu 醌:kun 醑:xu 醚:mi 醛:quan 采:cai 释:shi 里:li 重:zhong 量:liang 金:jin 鑫:xin 钆:ga 钇:yi 钐:shan 钙:gai 钠:na
钡:bei 钦:qin 钩:gou 钰:yu 钴:gu 钾:jia 铁:tie 铂:bo 铃:ling 铊:ta 铋:bi 铜:tong 铝:lü 铭:ming 铵:an 银:yin 链:lian
铿:keng 锂:li 锆:gao 锋:feng 锌:xin 锐:rui 锑:ti 锝:de 锡:xi 锦:jin 锭:ding 锰:meng 锵:qiang 锶:si 镁:mei 镇:zhen
镜:jing 镧:lan 镭:lei 长:chang 门:men 闭:bi 闯:chuang 闲:xian 间:jian 阁:ge 阔:kuo 防:fang 阳:yang 阴:yin 阿:a 附:fu
陆:lu 降:jiang 陷:xian 隆:long 隐:yin 雄:xiong 雅:ya 集:ji 雌:ci 雨:yu 雪:xue 雷:lei 雾:wu 霁:ji 震:zhen 霉:mei
霍:huo 霖:lin 霜:shuang 霡:mai 露:lu 青:qing 靓:liang 靖:jing 静:jing 靛:dian 非:fei 面:mian 革:ge 鞘:qiao 鞣:rou
韦:wei 韬:tao 韵:yun 顶:ding 顺:shun 顿:dun 颂:song 预:yu 颅:lu 颇:po 颊:jia 颐:yi 颖:ying 颗:ke 颜:yan 颠:dian
风:feng 飒:sa 飞:fei 食:shi 饮:yin 馈:kui 首:shou 香:xiang 馨:xin 马:ma 骁:xiao 验:yan 骨:gu 髓:sui 高:gao 鬼:gui
魏:wei 鱼:yu 鲁:lu 鲑:gui 鲨:sha 鲸:jing 鸟:niao 鸡:ji 鸣:ming 鸿:hong 鹅:e 鹿:lu 麝:she 麟:lin 麦:mai 麸:fu 麻:ma
黄:huang 黏:nian 默:mo 黛:dai 鼎:ding 鼠:shu 鼻:bi 齐:qi 龄:ling 龙:long"""

_PINYIN_DICT: dict[str, str] | None = None
_CJK = re.compile(r"[\u3400-\u9fff]")


def pinyin_dict() -> dict[str, str]:
    """字符 → 默认拼音（懒解析，进程内只解析一次）。"""
    global _PINYIN_DICT
    if _PINYIN_DICT is None:
        out: dict[str, str] = {}
        for part in _PINYIN_CHARS_TEXT.split():
            ch, _, py = part.partition(":")
            if ch and py:
                out[ch] = py
        _PINYIN_DICT = out
    return _PINYIN_DICT


# 多音字候选（默认读音见 pinyin_dict；这里只列“额外读音”，避免与表重复）
POLYPHONE_EXTRA: dict[str, tuple[str, ...]] = {
    '重': ('chong',),
    '长': ('zhang',),
    '行': ('hang',),
    '乐': ('yue',),
    '参': ('can',),
    '柏': ('bo',),
    '薄': ('bo',),
    '阿': ('e',),
    '熟': ('shou',),
    '血': ('xie',),
    '降': ('xiang',),
    '调': ('diao',),
    '都': ('du',),
    '发': ('fa',),
    '差': ('chai', 'ci'),
    '着': ('zhuo',),
    '和': ('huo',),
    '率': ('shuai',),
    '哪': ('nei',),
    '卡': ('qia',),
    '曾': ('zeng',),
    '单': ('shan',),
    '解': ('xie',),
    '藏': ('zang',),
    '枸': ('ju',),
    '桔': ('ju',),
    '便': ('pian',),
    '石': ('dan',),
    '术': ('zhu',),
    '大': ('dai',),
    '地': ('de',),
    '塞': ('se',),
    '壳': ('qiao',),
    '给': ('ji',),
    '曲': ('qu',),
    '佛': ('fu',),
    '觉': ('jiao',),
    '侧': ('zhai',),
    '削': ('xiao',),
    '舍': ('she',),
    '膏': ('gao',),
    '散': ('san',),
    '数': ('shu',),
    '中': ('zhong',),
    '为': ('wei',),
    '与': ('yu',),
    '校': ('jiao',),
    '艾': ('yi',),
}


def readings_of(ch: str) -> tuple[str, ...]:
    """单字读音候选：默认读音 + 多音字额外读音（去重、保持顺序）。"""
    default = pinyin_dict().get(ch)
    out = []
    if default:
        out.append(default)
    for extra in POLYPHONE_EXTRA.get(ch, ()):
        if extra not in out:
            out.append(extra)
    return tuple(out)


def _default_syllables(text: str) -> list[str]:
    """客户端口径的字串 → 音节列表：汉字用默认读音，ASCII 字母数字按单字符。"""
    table = pinyin_dict()
    syl: list[str] = []
    for ch in text or "":
        if "\u3400" <= ch <= "\u9fff":
            syl.append(table.get(ch, ""))
        elif ch.isascii() and ch.isalnum():
            syl.append(ch.lower())
    return [s for s in syl if s]


def _tokens_of_syllables(syl: list[str]) -> set[str]:
    toks: set[str] = set()
    for s in syl:
        toks.add("s:" + s)
    if len(syl) > 1:
        toks.add("j:" + "".join(syl))
        toks.add("i:" + "".join(x[0] for x in syl))
    return toks


def pinyin_tokens(text: str, polyphone: bool = False, max_variants: int = 8) -> list[str]:
    """汉字串 → token 集合（与客户端同口径）。

    polyphone=True 时额外生成多音字候选（最多 max_variants 个变体）：
      - 对每个多音字位置替换成额外读音，生成对应的 s:/j:/i: token；
      - 变体数量按「额外读音个数」截断，避免组合爆炸。
    默认 polyphone=False，与 app.js 的 _pinyin_tokens 完全一致。
    """
    default_syl = _default_syllables(text)
    toks = _tokens_of_syllables(default_syl)
    if not polyphone or not default_syl:
        return sorted(toks)
    table = pinyin_dict()
    # 逐字构建（与 _default_syllables 同口径：缺读音的汉字跳过），
    # 同时记录多音字位置 → 额外读音，避免下标错位。
    syl_all: list[str] = []
    extra_pos: list[tuple[int, list[str]]] = []
    for ch in text or "":
        if "\u3400" <= ch <= "\u9fff":
            p = table.get(ch)
            if not p:
                continue
            pos = len(syl_all)
            syl_all.append(p)
            alts = [x for x in POLYPHONE_EXTRA.get(ch, ()) if x and x != p]
            if alts:
                extra_pos.append((pos, alts))
        elif ch.isascii() and ch.isalnum():
            syl_all.append(ch.lower())
    variants = 0
    for pos, alts in extra_pos:
        for alt in alts:
            if variants >= max_variants:
                break
            syl = list(syl_all)
            syl[pos] = alt
            toks |= _tokens_of_syllables(syl)
            variants += 1
    return sorted(toks)


def compact_query(query: str) -> str:
    """拼音查询归一：小写、只留 ASCII 字母数字（与客户端 compact 口径一致）。"""
    s = (query or "").casefold()
    return "".join(ch for ch in s if ch.isascii() and ch.isalnum())


def query_tokens(query: str) -> list[str]:
    """拼音查询 → 候选 token 列表（顺序 = 客户端查找优先级 j > i > s）。

    客户端（app.js:3123）：
        PY_MAP.get('j:' + nq) || PY_MAP.get('i:' + nq) || PY_MAP.get('s:' + nq)
    """
    q = compact_query(query)
    if not q:
        return []
    if len(q) == 1:
        return ["s:" + q]
    return ["j:" + q, "i:" + q, "s:" + q]


def is_cjk_text(text: str) -> bool:
    return bool(_CJK.search(text or ""))


# 快照来源：site/build.py::_PINYIN_CHARS_TEXT（1,582 字）。
# 重新提取：python .tmp/pinyin-lib/gen_pinyin_lib.py（会与本模块的 pinyin_dict 对比）。
