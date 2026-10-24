# 手绘插画图标

本目录116张80×80透明PNG由illustrated_assets.py及item_expansion.py以QPainter三倍超采样绘制，使用圆角深棕描边、柔和填充、高光和底影，无外部素材或Unicode Emoji。

运行时同名PNG永远优先。更换画师图片时直接替换对应文件（建议80×80或更高分辨率等比例透明PNG），重启或在游戏设置点击「重新加载外观与图标」。加载器不会覆盖既有图；损坏图片仅使用内存矢量兜底，原文件不动。缺失图才自动生成PNG。个人素材不需要提交GitHub，请在后续协作中明确哪些画师图片可以发布。

| 文件 | 对应内容 |
| --- | --- |
| water.png | 温开水 |
| sugar.png | 白砂糖 |
| osmanthus.png | 桂花酒酿 |
| sesame.png | 黑芝麻糊 |
| strawberry.png | 草莓果酱 |
| matcha.png | 宇治抹茶粉 |
| chili.png | 变态辣油 |
| paper_star.png | 折纸星星 |
| flower_bouquet.png | 小花束 |
| music_box.png | 八音盒 |
| spinning_top.png | 陀螺 |
| cheese_room.png | 温馨奶酪屋 |
| sakura_room.png | 樱花甜梦屋 |
| matcha_room.png | 宇治茶室屋 |
| cloud_cushion.png | 云朵软垫 |
| lotus_cushion.png | 清新荷叶垫 |
| cat_paw_rug.png | 豪华猫爪地毯 |
| sunflower_painting.png | 向日葵挂画 |
| rice_clock.png | 糯米挂钟 |
| ficus_plant.png | 琴叶榕盆栽 |
| warm_lamp.png | 暖心落地灯 |
| wood_bowl.png | 朴素小木碗 |
| porcelain_bowl.png | 青花瓷汤碗 |
| sprout.png | 呆毛嫩芽 |
| crown.png | 迷你金皇冠 |
| sunglasses.png | 酷盖墨镜 |
| bow.png | 樱粉蝴蝶结 |
| steam.png | 暖心热气 |
| flip.png | 原地空翻 |
| clone.png | Q弹影分身 |
| ball.png | 芝麻弹力球 |
| screen_roll.png | 绕屏滚一圈 |
| coin.png | 糯米币 |
| avatar.png | 宠物头像兜底 |
| home.png | 小屋主页 |
| bag.png | 背包与投喂 |
| shop.png | 商城 |
| dress.png | 换装与小窝装修 |
| achievements.png | 成就与设置 |
| settings.png | 游戏设置 |
| desktop.png | 桌面宠物 |
| import_image.png | 本地PNG/GIF导入 |
| import_folder.png | 动作包文件夹 |
| import_zip.png | ZIP动作包 |
| template.png | 模板导出 |
| remove.png | 不佩戴/收起 |
| title.png | 称号铭牌 |
| debug.png | 开发调试 |
| lamp.png | 灯光开关 |
| first_poke.png | Q弹初体验 |
| first_drop.png | 高空抛物 |
| first_feed.png | 第一口甜 |
| first_pet.png | 温柔摸头 |
| flavors_three.png | 百味汤圆 |
| gifts_three.png | 勤俭持家 |
| level_three.png | 形影不离 |
| rapid_pokes.png | 无情铁手 |
| shake.png | 天旋地转 |
| rescue.png | 绝处逢生 |
| soul_infusion.png | 灵魂注入 |
| warm_home.png | 温馨小家 |
| level_1.png | Lv.1等级奖励 |
| level_2.png | Lv.2等级奖励 |
| level_3.png | Lv.3等级奖励 |
| level_4.png | Lv.4等级奖励 |
| level_5.png | Lv.5等级奖励 |
| level_6.png | Lv.6等级奖励 |

## V2.0新增长期奖励插画

| 文件 | 对应内容 |
| --- | --- |
| sunny_chime.png | 晴天风铃 |
| orange.png | 大吉小橘子 |
| disco.png | 迪斯科蹦迪 |
| camp_room.png | 星夜露营屋 |
| fireflies.png | 流光萤火虫 |
| sesame_friend.png | 芝麻小团子 |
| royal_rug.png | 皇家天鹅绒垫 |
| rainbow.png | 七彩祥云光环 |
| level_8.png / level_10.png / level_15.png / level_20.png / level_25.png / level_30.png | 对应等级里程碑徽章 |

以上为历史等级奖励图记录。本轮前已有87张图；本轮追加19张后共106张，原有图片保持原字节。2.0前端已移除个人皮肤导入入口。

## 首批道具与旧装扮重做（本地）

新增16件各使用同名ID.png，见[道具清单与验收](../../docs/首批道具扩充验收.md)。三个重做图标使用red_steam.png、cleanse_orange.png、champion_spotlight.png；原steam/orange/rainbow缓存保留。sprout、bow、fireflies仅为旧存档兼容保留，不再出现在新奖励与换装列表。所有既有PNG未被覆盖。

## Part 2 练习与走位（本地）

本批追加10张独立插画，共116张。沿用80×80透明PNG、3倍超采样、暖咖描边和明暗面；原106张PNG保持原字节，没有用新图覆盖旧缓存。运行与构建资源使用同一显式图标清单，仍优先读取画师同名本地图。

| 文件 | 对应内容 |
| --- | --- |
| gnar_workbook.png | 纳尔练习册 |
| practice_hourglass.png | 加练沙漏 |
| fist_bump_glove.png | 击拳手套 |
| postmatch_noodles.png | 赛后泡面 |
| late_practice_snack.png | 加练夜宵 |
| seven_goggles.png | 七号护目镜 |
| kiting_scarf.png | 拉扯围巾 |
| practice_room.png | 加练训练室 |
| summit_wall.png | 登峰岩壁 |
| reverse_flash.png | 反向闪现 |

[本批操作验收](../../docs/Part2练习与走位验收.md)。代码与素材已通过808项自动化及122项原生检查，纳入2026-10-24 main源码更新；EXE未重建。
