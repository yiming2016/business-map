//存号线地址数组
var xlurlarr = [
	{
		"img": 1,
		"name": "1号线",
		"nameen": "Line 1",
		"code": "0101"
	},
	{
		"img": 2,
		"name": "2号线",
		"nameen": "Line 2",
		"code": "0201"
	},
	{
		"img": 3,
		"name": "3号线",
		"nameen": "Line 3",
		"code": "0301"
	},
	{
		"img": 4,
		"name": "4号线",
		"nameen": "Line 4",
		"code": "0401"
	},
	{
		"img": 5,
		"name": "5号线",
		"nameen": "Line 5",
		"code": "0501"
	},
	{		
		"img": 6,
		"name": "6号线",
		"nameen": "Line 6",
		"code": "0601"
	},
	{		
		"img": 66,
		"name": "6号线支线",
		"nameen": "Line 6",
		"code": "6601"
	},
	{
		"img": 7,
		"name": "7号线",
		"nameen": "Line 7",
		"code": "0701"
	},
	{
		"img": 8,
		"name": "8号线",
		"nameen": "Line 8",
		"code": "0802"
	},
	{
		"img": 9,
		"name": "9号线",
		"nameen": "Line 9",
		"code": "0901"
	},
	{
		"img": 10,
		"name": "10号线",
		"nameen": "Line 10",
		"code": "1001"
	},
	{
		"img": 11,
		"name": "11号线",
		"nameen": "Line 11",
		"code": "1101"
	},
	{
		"img": 12,
		"name": "12号线",
		"nameen": "Line 12",
		"code": "1201"
	},{
		"img": 13,
		"name": "13号线",
		"nameen": "Line 13",
		"code": "1301"
	},
	{
		"img": 14,
		"name": "14号线",
		"nameen": "Line 14",
		"code": "1401"
	},
	{
		"img": 16,
		"name": "16号线",
		"nameen": "Line 16",
		"code": "1601"
	},
	{
		"img": 20,
		"name": "20号线",
		"nameen": "Line 20",
		"code": "2001"
	}
];

//存站点地址数组
var zdurl = [
	{  //1号线
		line:'1',
		zdList:[
			{
				name:"罗湖",
				nameen:"Luohu",
				code:"0101"
			},
			{
				name:"国贸",
				nameen:"Guomao",
				code:"0102"
			},
			{
				name:"老街",
				nameen:"Laojie",
				code:"0103"
			},
			{
				name:"大剧院",
				nameen:"Grand Theater",
				code:"0104"
			},
			{
				name:"科学馆",
				nameen:"Science Museum",
				code:"0105"
			},
			{
				name:"华强路",
				nameen:"Huaqiang Rd",
				code:"0106"
			},
			{
				name:"岗厦",
				nameen:"Gangxia",
				code:"0107"
			},
			{
				name:"会展中心",
				nameen:"Convention & Exhibition Center",
				code:"0108"
			},
			{
				name:"购物公园",
				nameen:"Shopping Park",
				code:"0109"
			},
			{
				name:"香蜜湖",
				nameen:"Xiangmihu",
				code:"0110"
			},
			{
				name:"车公庙",
				nameen:"Chegongmiao",
				code:"0111"
			},
			{
				name:"竹子林",
				nameen:"Zhuzilin",
				code:"0112"
			},
			{
				name:"侨城东",
				nameen:"Qiaocheng East",
				code:"0113"
			},
			{
				name:"华侨城",
				nameen:"OCT",
				code:"0114"
			},
			{
				name:"世界之窗",
				nameen:"Window of the World",
				code:"0115"
			},
			{
				name:"白石洲",
				nameen:"Baishizhou",
				code:"0116"
			},
			{
				name:"高新园",
				nameen:"Hi-Tech Park",
				code:"0117"
			},
			{
				name:"深大",
				nameen:"Shenzhen University",
				code:"0118"
			},
			{
				name:"桃园",
				nameen:"Taoyuan",
				code:"0119"
			},
			{
				name:"大新",
				nameen:"Daxin",
				code:"0120"
			},
			{
				name:"鲤鱼门",
				nameen:"Liyumen",
				code:"0121"
			},
			{
				name:"前海湾",
				nameen:"Qianhaiwan",
				code:"0122"
			},
			{
				name:"新安",
				nameen:"Xin'an",
				code:"0123"
			},
			{
				name:"宝安中心",
				nameen:"Bao'an Center",
				code:"0124"
			},
			{
				name:"宝体",
				nameen:"Bao'an Stadium",
				code:"0125"
			},
			{
				name:"坪洲",
				nameen:"Pingzhou",
				code:"0126"
			},
			{
				name:"西乡",
				nameen:"Xixiang",
				code:"0127"
			},
			{
				name:"固戍",
				nameen:"Gushu",
				code:"0128"
			},
			{
				name:"后瑞",
				nameen:"Hourui",
				code:"0129"
			},
			{
				name:"机场东",
				nameen:"Airport East",
				code:"0130"
			},
		]
	},
	{  //2号线
		line:'2',
		zdList:[
			{
				name:"赤湾",
				nameen:"Chiwan",
				code:"0201"
			},
			{
				name:"蛇口港",
				nameen:"Shekou Port",
				code:"0202"
			},
			{
				name:"海上世界",
				nameen:"Sea World",
				code:"0203"
			},
			{
				name:"水湾",
				nameen:"Shuiwan",
				code:"0204"
			},
			{
				name:"东角头",
				nameen:"Dongjiaotou",
				code:"0205"
			},
			{
				name:"湾厦",
				nameen:"Wanxia",
				code:"0206"
			},
			{
				name:"海月",
				nameen:"Haiyue",
				code:"0207"
			},
			{
				name:"登良",
				nameen:"Dengliang",
				code:"0208"
			},
			{
				name:"后海",
				nameen:"Houhai",
				code:"0209"
			},
			{
				name:"科苑",
				nameen:"Keyuan",
				code:"0210"
			},
			{
				name:"红树湾",
				nameen:"Hongshuwan",
				code:"0211"
			},
			{
				name:"世界之窗",
				nameen:"Window of the World",
				code:"0212"
			},
			{
				name:"侨城北",
				nameen:"Qiaocheng North",
				code:"0213"
			},
			{
				name:"深康",
				nameen:"Shenkang",
				code:"0214"
			},
			{
				name:"安托山",
				nameen:"Antuo Hill",
				code:"0215"
			},
			{
				name:"侨香",
				nameen:"Qiaoxiang",
				code:"0216"
			},
			{
				name:"香蜜",
				nameen:"Xiangmi",
				code:"0217"
			},
			{
				name:"香梅北",
				nameen:"Xiangmei North",
				code:"0218"
			},
			{
				name:"景田",
				nameen:"Jingtian",
				code:"0219"
			},
			{
				name:"莲花西",
				nameen:"Lianhua West",
				code:"0220"
			},
			{
				name:"福田",
				nameen:"Futian",
				code:"0221"
			},
			{
				name:"市民中心",
				nameen:"Civic Center",
				code:"0222"
			},
			{
				name:"岗厦北",
				nameen:"Gangxia North",
				code:"0223"
			},
			{
				name:"华强北",
				nameen:"Huaqiang North",
				code:"0224"
			},
			{
				name:"燕南",
				nameen:"Yannan",
				code:"0225"
			},
			{
				name:"大剧院",
				nameen:"Grand Theater",
				code:"0226"
			},
			{
				name:"湖贝",
				nameen:"Hubei",
				code:"0227"
			},
			{
				name:"黄贝岭",
				nameen:"Huangbeiling",
				code:"0228"
			},
			{
				name:"新秀",
				nameen:"Xinxiu",
				code:"0229"
			},
			{
				name:"莲塘口岸",
				nameen:"Liantang Checkpoint",
				code:"0230"
			},
			{
				name:"仙湖路",
				nameen:"Xianhu Rd",
				code:"0231"
			},
			{
				name:"莲塘",
				nameen:"Liantang",
				code:"0232"
			},
		]
	},
	{  //3号线
		line:'3',
		zdList:[
			{
				name:"福保",
				nameen:"Futian Bonded Area",
				code:"0301"
			},
			{
				name:"益田",
				nameen:"Yitian",
				code:"0302"
			},
			{
				name:"石厦",
				nameen:"Shixia",
				code:"0303"
			},
			{
				name:"购物公园",
				nameen:"Shopping Park",
				code:"0304"
			},
			{
				name:"福田",
				nameen:"Futian",
				code:"0305"
			},
			{
				name:"少年宫",
				nameen:"Children's Palace",
				code:"0306"
			},
			{
				name:"莲花村",
				nameen:"Lianhuacun",
				code:"0307"
			},
			{
				name:"华新",
				nameen:"Huaxin",
				code:"0308"
			},
			{
				name:"通新岭",
				nameen:"Tongxinling",
				code:"0309"
			},
			{
				name:"红岭",
				nameen:"Hongling",
				code:"0310"
			},
			{
				name:"老街",
				nameen:"Laojie",
				code:"0311"
			},
			{
				name:"晒布",
				nameen:"Shaibu",
				code:"0312"
			},
			{
				name:"翠竹",
				nameen:"Cuizhu",
				code:"0313"
			},
			{
				name:"田贝",
				nameen:"Tianbei",
				code:"0314"
			},
			{
				name:"水贝",
				nameen:"Shuibei",
				code:"0315"
			},
			{
				name:"草埔",
				nameen:"Caopu",
				code:"0316"
			},
			{
				name:"布吉",
				nameen:"Buji",
				code:"0317"
			},
			{
				name:"木棉湾",
				nameen:"Mumianwan",
				code:"0318"
			},
			{
				name:"大芬",
				nameen:"Dafen",
				code:"0319"
			},
			{
				name:"丹竹头",
				nameen:"Danzhutou",
				code:"0320"
			},
			{
				name:"六约",
				nameen:"Liuyue",
				code:"0321"
			},
			{
				name:"塘坑",
				nameen:"Tangkeng",
				code:"0322"
			},
			{
				name:"横岗",
				nameen:"Henggang",
				code:"0323"
			},
			{
				name:"永湖",
				nameen:"Yonghu",
				code:"0324"
			},
			{
				name:"荷坳",
				nameen:"He'ao",
				code:"0325"
			},
			{
				name:"大运",
				nameen:"Universiade",
				code:"0326"
			},
			{
				name:"爱联",
				nameen:"Ailian",
				code:"0327"
			},
			{
				name:"吉祥",
				nameen:"Jixiang",
				code:"0328"
			},
			{
				name:"龙城广场",
				nameen:"Longcheng Square",
				code:"0329"
			},
			{
				name:"南联",
				nameen:"Nanlian",
				code:"0330"
			},
			{
				name:"双龙",
				nameen:"Shuanglong",
				code:"0331"
			},{
				name:"梨园",
				nameen:"Liyuan",
				code:"0332"
			},{
				name:"新生",
				nameen:"Xinsheng",
				code:"0333"
			},{
				name:"坪西",
				nameen:"Pingxi",
				code:"0334"
			},{
				name:"低碳城",
				nameen:"Low-carbon City",
				code:"0335"
			},{
				name:"白石塘",
				nameen:"Baishitang",
				code:"0336"
			},{
				name:"富坪",
				nameen:"Fuping",
				code:"0337"
			},{
				name:"坪地六联",
				nameen:"Pingdi Liulian",
				code:"0338"
			},
		]
	},
	{  //4号线
		line:'4',
		zdList:[
			{
				name:"福田口岸",
				nameen:"Futian Checkpoint",
				code:"0401"
			},
			{
				name:"福民",
				nameen:"Fumin",
				code:"0402"
			},
			{
				name:"会展中心",
				nameen:"Convention & Exhibition Center",
				code:"0403"
			},
			{
				name:"市民中心",
				nameen:"Civic Center",
				code:"0404"
			},
			{
				name:"少年宫",
				nameen:"Children's Palace",
				code:"0405"
			},
			{
				name:"莲花北",
				nameen:"Lianhua North",
				code:"0406"
			},
			{
				name:"上梅林",
				nameen:"Shangmeilin",
				code:"0407"
			},
			{
				name:"民乐",
				nameen:"Minle",
				code:"0408"
			},
			{
				name:"白石龙",
				nameen:"Baishilong",
				code:"0409"
			},
			{
				name:"深圳北",
				nameen:"Shenzhen North Station",
				code:"0410"
			},
			{
				name:"红山",
				nameen:"Hongshan",
				code:"0411"
			},
			{
				name:"上塘",
				nameen:"Shangtang",
				code:"0412"
			},
			{
				name:"龙胜",
				nameen:"Longsheng",
				code:"0413"
			},
			{
				name:"龙华",
				nameen:"Longhua",
				code:"0414"
			},
			{
				name:"清湖",
				nameen:"Qinghu",
				code:"0415"
			},
			{
				name:"清湖北",
				nameen:"Qinghu North",
				code:"0416"
			},
			{
				name:"竹村",
				nameen:"Zhucun",
				code:"0417"
			},
			{
				name:"茜坑",
				nameen:"Xikeng",
				code:"0418"
			},
			{
				name:"长湖",
				nameen:"Changhu",
				code:"0419"
			},
			{
				name:"观澜",
				nameen:"Guanlan",
				code:"0420"
			},
			{
				name:"松元厦",
				nameen:"Songyuanxia",
				code:"0421"
			},
			{
				name:"观澜湖	",
				nameen:"Mission Hills",
				code:"0422"
			},
			{
				name:"牛湖",
				nameen:"Niuhu",
				code:"0423"
			},
		]
	},
	{  //5号线
		line:'5',
		zdList:[
			{
				name:"赤湾",
				nameen:"Chiwan",
				code:"0501"
			},
			{
				name:"荔湾",
				nameen:"Liwan",
				code:"0502"
			},
			{
				name:"铁路公园",
				nameen:"Railway Park",
				code:"0503"
			},
			{
				name:"妈湾",
				nameen:"Mawan",
				code:"0504"
			},
			{
				name:"前湾公园",
				nameen:"Qianwan Park",
				code:"0505"
			},
			{
				name:"前湾",
				nameen:"Qianwan",
				code:"0506"
			},
			{
				name:"桂湾",
				nameen:"Guiwan",
				code:"0507"
			},
			{
				name:"前海湾",
				nameen:"Qianhaiwan",
				code:"0508"
			},
			{
				name:"临海",
				nameen:"Linhai",
				code:"0509"
			},
			{
				name:"宝华",
				nameen:"Baohua",
				code:"0510"
			},
			{
				name:"宝安中心",
				nameen:"Bao'an Center",
				code:"0511"
			},
			{
				name:"翻身",
				nameen:"Fanshen",
				code:"0512"
			},
			{
				name:"灵芝",
				nameen:"Lingzhi",
				code:"0513"
			},
			{
				name:"洪浪北",
				nameen:"Honglang North",
				code:"0514"
			},
			{
				name:"兴东",
				nameen:"Xingdong",
				code:"0515"
			},
			{
				name:"留仙洞",
				nameen:"Liuxiandong",
				code:"0516"
			},
			{
				name:"西丽",
				nameen:"Xili",
				code:"0517"
			},
			{
				name:"大学城",
				nameen:"University Town",
				code:"0518"
			},
			{
				name:"塘朗",
				nameen:"Tanglang",
				code:"0519"
			},
			{
				name:"长岭陂",
				nameen:"Changlingpi",
				code:"0520"
			},
			{
				name:"深圳北",
				nameen:"Shenzhen North Station",
				code:"0521"
			},
			{
				name:"民治",
				nameen:"Minzhi",
				code:"0522"
			},
			{
				name:"五和",
				nameen:"Wuhe",
				code:"0523"
			},
			{
				name:"坂田",
				nameen:"Bantian",
				code:"0524"
			},
			{
				name:"杨美",
				nameen:"Yangmei",
				code:"0525"
			},
			{
				name:"上水径",
				nameen:"Shangshuijing",
				code:"0526"
			},
			{
				name:"下水径",
				nameen:"Xiashuijing",
				code:"0527"
			},
			{
				name:"长龙",
				nameen:"Changlong",
				code:"0528"
			},
			{
				name:"布吉",
				nameen:"Buji",
				code:"0529"
			},
			{
				name:"百鸽笼",
				nameen:"Baigelong",
				code:"0530"
			},
			{
				name:"布心",
				nameen:"Buxin",
				code:"0531"
			},
			{
				name:"太安",
				nameen:"Tai'an",
				code:"0532"
			},
			{
				name:"怡景",
				nameen:"Yijing",
				code:"0533"
			},
			{
				name:"黄贝岭",
				nameen:"Huangbeiling",
				code:"0534"
			},
			{
				name:"湖贝",
				nameen:"Hubei",
				code:"0535"
			},
			{
				name:"东门",
				nameen:"Dongmen",
				code:"0536"
			},{
				name:"大剧院",
				nameen:"Grand Theater",
				code:"0537"
			},
		]
	},
	{  //6号线
		line:'6',
		zdList:[
			{
				name:"科学馆",
				nameen:"Science Museum",
				code:"0601"
			},
			{
				name:"通新岭",
				nameen:"Tongxinling",
				code:"0602"
			},
			{
				name:"体育中心",
				nameen:"Sports Center",
				code:"0603"
			},
			{
				name:"八卦岭",
				nameen:"Bagualing",
				code:"0604"
			},
			{
				name:"银湖",
				nameen:"Yinhu",
				code:"0605"
			},
			{
				name:"翰岭",
				nameen:"Hanling",
				code:"0606"
			},
			{
				name:"梅林关",
				nameen:"Meilinguan",
				code:"0607"
			},
			{
				name:"深圳北",
				nameen:"Shenzhen North Station",
				code:"0608"
			},
			{
				name:"红山",
				nameen:"Hongshan",
				code:"0609"
			},
			{
				name:"上芬",
				nameen:"Shangfen",
				code:"0610"
			},
			{
				name:"元芬",
				nameen:"Yuanfen",
				code:"0611"
			},
			{
				name:"阳台山东",
				nameen:"Yangtai Mountain East",
				code:"0612"
			},
			{
				name:"官田",
				nameen:"Guantian",
				code:"0613"
			},
			{
				name:"上屋",
				nameen:"Shangwu",
				code:"0614"
			},
			{
				name:"长圳",
				nameen:"Changzhen",
				code:"0615"
			},
			{
				name:"凤凰城",
				nameen:"Fenghuang Town",
				code:"0616"
			},
			{
				name:"光明大街",
				nameen:"Guangming St",
				code:"0617"
			},
			{
				name:"光明",
				nameen:"Guangming",
				code:"0618"
			},
			{
				name:"科学公园",
				nameen:"Science Park",
				code:"0619"
			},
			{
				name:"楼村",
				nameen:"Loucun",
				code:"0620"
			},
			{
				name:"红花山",
				nameen:"Honghuashan",
				code:"0621"
			},
			{
				name:"公明广场",
				nameen:"Gongming Square",
				code:"0622"
			},
			{
				name:"合水口",
				nameen:"Heshuikou",
				code:"0623"
			},
			{
				name:"薯田埔",
				nameen:"Shutianpu",
				code:"0624"
			},
			{
				name:"松岗公园",
				nameen:"Songgang Park",
				code:"0625"
			},
			{
				name:"溪头",
				nameen:"Xitou",
				code:"0626"
			},
			{
				name:"松岗",
				nameen:"Songgang",
				code:"0627"
			},
		]
	},
	{  //6号线支线
		line:'66',
		zdList:[
			{
				name:"光明城",
				nameen:"Guangmingcheng",
				code:"6601"
			},{
				name:"虹桥公园",
				nameen:"Hongqiao Park",
				code:"6602"
			},{
				name:"碧眼",
				nameen:"BiYan",
				code:"6603"
			},{
				name:"光明",
				nameen:"Guangming",
				code:"6604"
			},
			{
				name:"圳美",
				nameen:"Zhenmei",
				code:"6605"
			},
			{
				name:"中大",
				nameen:"Sun Yat-sen University Station",
				code:"6606"
			},
			{
				name:"深理工",
				nameen:"SUAT",
				code:"6607"
			},
			]
	},
	{  //7号线
		line:'7',
		zdList:[
			{
				name:"深大丽湖",
				nameen:"SZU Lihu Campus",
				code:"0701"
			},
			{
				name:"北大",
				nameen:"Peking University",
				code:"0702"
			},
			{
				name:"西丽湖",
				nameen:"Xili Lake",
				code:"0703"
			},
			{
				name:"西丽",
				nameen:"Xili",
				code:"0704"
			},
			{
				name:"茶光",
				nameen:"Chaguang",
				code:"0705"
			},
			{
				name:"珠光",
				nameen:"Zhuguang",
				code:"0706"
			},
			{
				name:"龙井",
				nameen:"Longjing",
				code:"0707"
			},
			{
				name:"桃源村",
				nameen:"Taoyuancun",
				code:"0708"
			},
			{
				name:"深云",
				nameen:"Shenyun",
				code:"0709"
			},
			{
				name:"安托山",
				nameen:"Antuo Hill",
				code:"0710"
			},
			{
				name:"农林",
				nameen:"Nonglin",
				code:"0711"
			},
			{
				name:"车公庙",
				nameen:"Chegongmiao",
				code:"0712"
			},
			{
				name:"上沙",
				nameen:"Shangsha",
				code:"0713"
			},
			{
				name:"沙尾",
				nameen:"Shawei",
				code:"0714"
			},
			{
				name:"石厦",
				nameen:"Shixia",
				code:"0715"
			},
			{
				name:"皇岗村",
				nameen:"Huanggangcun",
				code:"0716"
			},
			{
				name:"福民",
				nameen:"Fumin",
				code:"0717"
			},
			{
				name:"皇岗口岸",
				nameen:"Huanggang Checkpoint",
				code:"0718"
			},
			
			{
				name:"赤尾",
				nameen:"Chiwei",
				code:"0719"
			},
			{
				name:"华强南",
				nameen:"Huaqiang South",
				code:"0720"
			},
			{
				name:"华强北",
				nameen:"Huaqiang North",
				code:"0721"
			},
			{
				name:"华新",
				nameen:"Huaxin",
				code:"0722"
			},
			{
				name:"黄木岗",
				nameen:"Huangmugang",
				code:"0723"
			},
			{
				name:"八卦岭",
				nameen:"Bagualing",
				code:"0724"
			},
			{
				name:"红岭北",
				nameen:"Hongling North",
				code:"0725"
			},
			{
				name:"笋岗",
				nameen:"Sungang",
				code:"0726"
			},
			{
				name:"洪湖",
				nameen:"Honghu",
				code:"0727"
			},
			{
				name:"田贝",
				nameen:"Tianbei",
				code:"0728"
			},
			{
				name:"太安",
				nameen:"Tai'an",
				code:"0729"
			},	
		]
	},
	{  //8号线
		line:'8',
		zdList:[
			{
				name:"梧桐山南",
				nameen:"Wutong Mountain South",
				code:"0802"
			},
			{
				name:"沙头角",
				nameen:"Shatoujiao",
				code:"0803"
			},
			{
				name:"海山",
				nameen:"Haishan",
				code:"0804"
			},
			{
				name:"盐田港西",
				nameen:"Yantian Port West",
				code:"0805"
			},
			{
				name:"深外高中",
				nameen:"Shenwai Senior Campus",
				code:"0806"
			},
			{
				name:"盐田路",
				nameen:"Yantian Rd",
				code:"0807"
			},	
			{
				name:"鸿安围",
				nameen:"Honganwei",
				code:"0808"
			},	
			{
				name:"盐田墟",
				nameen:"Yantianxu",
				code:"0809"
			},	
			{
				name:"大梅沙",
				nameen:"Dameisha",
				code:"0810"
			},	
			{
				name:"小梅沙",
				nameen:"Xiaomeisha",
				code:"0811"
			},{
				name:"溪涌",
				nameen:"Xichong",
				code:"0812"
			},				
		]
	},
	{  //9号线
		line:'9',
		zdList:[
			{
				name:"前湾",
				nameen:"Qianwan",
				code:"0901"
			},
			{
				name:"梦海",
				nameen:"Menghai",
				code:"0902"
			},
			{
				name:"怡海",
				nameen:"Yihai",
				code:"0903"
			},
			{
				name:"荔林",
				nameen:"Litchi Orchards",
				code:"0904"
			},
			{
				name:"南油西",
				nameen:"Nanyou West",
				code:"0905"
			},
			{
				name:"南油",
				nameen:"Nanyou",
				code:"0906"
			},
			{
				name:"南山书城",
				nameen:"Nanshan Book Mall",
				code:"0907"
			},
			{
				name:"深大南",
				nameen:"Shenzhen University South",
				code:"0908"
			},
			{
				name:"粤海门",
				nameen:"Yuehaimen",
				code:"0909"
			},
			{
				name:"高新南",
				nameen:"High-tech South",
				code:"0910"
			},
			{
				name:"红树湾南",
				nameen:"Hongshuwan South",
				code:"0911"
			},
			{
				name:"深湾",
				nameen:"Shenwan",
				code:"0912"
			},
			{
				name:"深圳湾公园",
				nameen:"Shenzhen Bay Park",
				code:"0913"
			},
			{
				name:"下沙",
				nameen:"Xiasha",
				code:"0914"
			},
			{
				name:"车公庙",
				nameen:"Chengongmiao",
				code:"0915"
			},
			{
				name:"香梅",
				nameen:"Xiangmei",
				code:"0916"
			},
			{
				name:"景田",
				nameen:"Jingtian",
				code:"0917"
			},
			{
				name:"梅景",
				nameen:"Meijing",
				code:"0918"
			},
			{
				name:"下梅林",
				nameen:"Xiameilin",
				code:"0919"
			},
			{
				name:"梅村",
				nameen:"Meicun",
				code:"0920"
			},
			{
				name:"上梅林",
				nameen:"Shangmeilin",
				code:"0921"
			},
			{
				name:"孖岭",
				nameen:"Maling",
				code:"0922"
			},
			{
				name:"银湖",
				nameen:"Yinhu",
				code:"0923"
			},
			{
				name:"泥岗",
				nameen:"Nigang",
				code:"0924"
			},
			{
				name:"红岭北",
				nameen:"Hongling North",
				code:"0925"
			},
			{
				name:"园岭",
				nameen:"Yuanling",
				code:"0926"
			},
			{
				name:"红岭",
				nameen:"Hongling",
				code:"0927"
			},
			{
				name:"红岭南",
				nameen:"Hongling South",
				code:"0928"
			},
			{
				name:"鹿丹村",
				nameen:"Ludancun",
				code:"0929"
			},
			{
				name:"人民南",
				nameen:"Renmin South",
				code:"0930"
			},
			{
				name:"向西村",
				nameen:"Xiangxicun",
				code:"0931"
			},
			{
				name:"文锦",
				nameen:"Wenjin",
				code:"0932"
			},
		]
	},
	{  //10号线
		line:'10',
		zdList:[
			{
				name:"福田口岸",
				nameen:"Futian Checkpoint",
				code:"1001"
			},
			{
				name:"福民",
				nameen:"Fumin",
				code:"1002"
			},
			{
				name:"岗厦",
				nameen:"Gangxia",
				code:"1003"
			},
			{
				name:"岗厦北",
				nameen:"Gangxia North",
				code:"1004"
			},
			{
				name:"莲花村",
				nameen:"Lianhuacun",
				code:"1005"
			},
			{
				name:"冬瓜岭",
				nameen:"Donggualing",
				code:"1006"
			},
			{
				name:"孖岭",
				nameen:"Maling",
				code:"1007"
			},
			{
				name:"雅宝",
				nameen:"Yabao",
				code:"1008"
			},
			{
				name:"南坑",
				nameen:"Nankeng",
				code:"1009"
			},
			{
				name:"光雅园",
				nameen:"Guangyayuan",
				code:"1010"
			},
			{
				name:"五和",
				nameen:"Wuhe",
				code:"1011"
			},
			{
				name:"坂田北",
				nameen:"Bantian North",
				code:"1012"
			},
			{
				name:"贝尔路",
				nameen:"Bei'er Rd",
				code:"1013"
			},
			{
				name:"华为",
				nameen:"Huawei",
				code:"1014"
			},
			{
				name:"岗头",
				nameen:"Gangtou",
				code:"1015"
			},
			{
				name:"雪象",
				nameen:"Xuexiang",
				code:"1016"
			},
			{
				name:"甘坑",
				nameen:"Gankeng",
				code:"1017"
			},
			{
				name:"凉帽山",
				nameen:"Liangmao Hill",
				code:"1018"
			},
			{
				name:"上李朗",
				nameen:"Shanglilang",
				code:"1019"
			},
			{
				name:"木古",
				nameen:"Mugu",
				code:"1020"
			},
			{
				name:"华南城",
				nameen:"Huanancheng",
				code:"1021"
			},
			{
				name:"禾花",
				nameen:"Hehua",
				code:"1022"
			},
			{
				name:"平湖",
				nameen:"Pinghu",
				code:"1023"
			},
			{
				name:"双拥街",
				nameen:"Shuangyong St",
				code:"1024"
			},
		]
	},
	{  //11号线
		line:'11',
		zdList:[
			{
				name:"红岭南",
				nameen:"Hongling South",
				code:"1101"
			},
			{
				name:"华强南",
				nameen:"Huaqiang South",
				code:"1102"
			},{
				name:"福星",
				nameen:"Fuxing",
				code:"1103"
			},
			{
				name:"岗厦北",
				nameen:"Gangxia North",
				code:"1104"
			},
			{
				name:"福田",
				nameen:"Futian",
				code:"1105"
			},
			{
				name:"车公庙",
				nameen:"Chegongmiao",
				code:"1106"
			},
			{
				name:"红树湾南",
				nameen:"Hongshuwan South",
				code:"1107"
			},
			{
				name:"后海",
				nameen:"Houhai",
				code:"1108"
			},
			{
				name:"南山",
				nameen:"Nanshan",
				code:"1109"
			},
			{
				name:"前海湾",
				nameen:"Qianhaiwan",
				code:"1110"
			},
			{
				name:"宝安",
				nameen:"Bao'an",
				code:"1111"
			},
			{
				name:"碧海湾",
				nameen:"Bihaiwan",
				code:"1112"
			},
			{
				name:"机场",
				nameen:"Airport",
				code:"1113"
			},
			{
				name:"机场北",
				nameen:"Airport North",
				code:"1114"
			},
			{
				name:"福永",
				nameen:"Fuyong",
				code:"1115"
			},
			{
				name:"桥头",
				nameen:"Qiaotou",
				code:"1116"
			},
			{
				name:"塘尾",
				nameen:"Tangwei",
				code:"1117"
			},
			{
				name:"马安山",
				nameen:"Ma'anshan",
				code:"1118"
			},
			{
				name:"沙井",
				nameen:"Shajing",
				code:"1119"
			},
			{
				name:"后亭",
				nameen:"Houting",
				code:"1120"
			},
			{
				name:"松岗",
				nameen:"Songgang",
				code:"1121"
			},
			{
				name:"碧头",
				nameen:"Bitou",
				code:"1122"
			},
		]
	},
	{  //12号线
		line:'12',
		zdList:[
			{
				name:"左炮台东",
				nameen:"Zuopaotai East",
				code:"1201"
			},
			{
				name:"太子湾",
				nameen:"Taiziwan",
				code:"1202"
			},
			{
				name:"海上世界",
				nameen:"Sea World",
				code:"1203"
			},
			{
				name:"花果山",
				nameen:"Huaguoshan",
				code:"1204"
			},
			{
				name:"四海",
				nameen:"Sihai",
				code:"1205"
			},
			{
				name:"南油",
				nameen:"Nanyou",
				code:"1206"
			},
			{
				name:"南光",
				nameen:"Nanguang",
				code:"1207"
			},
			{
				name:"南山",
				nameen:"Nanshan",
				code:"1208"
			},
			{
				name:"桃园",
				nameen:"Taoyuan",
				code:"1209"
			},
			{
				name:"南头古城",
				nameen:"Nantou Ancient City",
				code:"1210"
			},
			{
				name:"中山公园",
				nameen:"Zhongshan Park",
				code:"1211"
			},
			{
				name:"同乐南",
				nameen:"Tongle South",
				code:"1212"
			},
			{
				name:"新安公园",
				nameen:"Xin'an Park",
				code:"1213"
			},
			{
				name:"灵芝",
				nameen:"Lingzhi",
				code:"1214"
			},
			{
				name:"上川",
				nameen:"Shangchuan",
				code:"1215"
			},
			{
				name:"流塘",
				nameen:"Liutang",
				code:"1216"
			},
			{
				name:"宝安客运站",
				nameen:"Bao'an Passenger Transport Terminal",
				code:"1217"
			},
			{
				name:"宝田一路",
				nameen:"Baotian 1st Road",
				code:"1218"
			},
			{
				name:"平峦山",
				nameen:"Pingluan Hill",
				code:"1219"
			},
			{
				name:"西乡桃源",
				nameen:"Xixiang Taoyuan",
				code:"1220"
			},
			{
				name:"钟屋南",
				nameen:"Zhongwu South",
				code:"1221"
			},
			{
				name:"黄田",
				nameen:"Huangtian",
				code:"1222"
			},
			{
				name:"兴围",
				nameen:"Xingwei",
				code:"1223"
			},
			{
				name:"机场东",
				nameen:"Airport East",
				code:"1224"
			},
			{
				name:"福围",
				nameen:"Fuwei",
				code:"1225"
			},
			{
				name:"怀德",
				nameen:"Huaide",
				code:"1226"
			},
			{
				name:"福永",
				nameen:"Fuyong",
				code:"1227"
			},
			{
				name:"桥头西",
				nameen:"Qiaotou West",
				code:"1228"
			},
			{
				name:"福海西",
				nameen:"Fuhai West",
				code:"1229"
			},
			{
				name:"国展",
				nameen:"Shenzhen World",
				code:"1230"
			},
			{
				name:"国展北",
				nameen:"Shenzhen World North",
				code:"1231"
			},
			{
				name:"海上田园南",
				nameen:"Waterlands Resort South",
				code:"1232"
			},{
				name:"海上田园东",
				nameen:"Waterlands Resort East",
				code:"1233"
			},
			{
				name:"蚝乡",
				nameen:"HaoXiang",
				code:"1234"
			},
			{
				name:"沙蚝",
				nameen:"Shahao",
				code:"1235"
			},
			{
				name:"沙井古墟",
				nameen:"Shajing Ancient Market",
				code:"1236"
			},{
				name:"步涌",
				nameen:"Buchong",
				code:"1237"
			},{
				name:"朗下",
				nameen:"Langxia",
				code:"1238"
			},{
				name:"松岗",
				nameen:"Songgang",
				code:"1239"
			},
		]
	},
	{  //13号线
		line:'13',
		zdList:[
			{
				name:"深圳湾口岸",
				nameen:"Shenzhenwankouan",
				code:"1301"
			},{
				name:"人才公园",
				nameen:"Rencaigongyuan",
				code:"1302"
			},{
				name:"后海",
				nameen:"Houhai",
				code:"1303"
			},{
				name:"科苑",
				nameen:"Keyuan",
				code:"1304"
			},{
				name:"粤海门",
				nameen:"Yuehaimen",
				code:"1305"
			},{
				name:"深大",
				nameen:"Shenda",
				code:"1306"
			},{
				name:"高新中",
				nameen:"Gaoxinzhong",
				code:"1307"
			},{
				name:"高新北",
				nameen:"Gaoxin North",
				code:"1308"
			},{
				name:"石鼓",
				nameen:"Shigu",
				code:"1309"
			},{
				name:"留仙洞",
				nameen:"liuxiandong",
				code:"1310"
			},{
				name:"百旺",
				nameen:"Baiwang-HKU",
				code:"1311"
			},{
				name:"应人石",
				nameen:"yingrenshi",
				code:"1312"
			},{
				name:"罗租",
				nameen:"luozu",
				code:"1313"
			},{
				name:"石岩",
				nameen:"Shiyan",
				code:"1314"
			},{
				name:"上屋",
				nameen:"Shangwu",
				code:"1315"
			},{
				name:"红坳公园",
				nameen:"Hongao Park",
				code:"1316"
			},{
				name:"光明城",
				nameen:"Guangmingcheng",
				code:"1317"
			},
			{
				name:"德雅路",
				nameen:"Deya Rd",
				code:"1318"
			},{
				name:"凤凰城",
				nameen:"Fenghuang Town",
				code:"1319"
			},{
				name:"月亮路",
				nameen:"Yueliang Rd",
				code:"1320"
			},{
				name:"将围",
				nameen:"Jiangwei",
				code:"1321"
			},{
				name:"新庄",
				nameen:"Xinzhuang",
				code:"1322"
			},{
				name:"公明广场",
				nameen:"Gongming Square",
				code:"1323"
			},{
				name:"上村",
				nameen:"Shangcun",
				code:"1324"
			},{
				name:"下村",
				nameen:"Xiacun",
				code:"1325"
			},{
				name:"李松蓢",
				nameen:"Lisonglang",
				code:"1326"
			},
			
	]
	},
	{  //14号线
		line:'14',
		zdList:[
			{
				name:"岗厦北",
				nameen:"Gangxia North",
				code:"1401"
			},
			{
				name:"黄木岗",
				nameen:"Huangmugang",
				code:"1402"
			},
			{
				name:"罗湖北",
				nameen:"Luohu  North",
				code:"1403"
			},
			{
				name:"布吉",
				nameen:"Buji",
				code:"1404"
			},
			{
				name:"石芽岭",
				nameen:"Shiyaling",
				code:"1405"
			},
			{
				name:"六约北",
				nameen:"Liuyue North",
				code:"1406"
			},
			{
				name:"四联",
				nameen:"四联",
				code:"1407"
			},
			{
				name:"坳背",
				nameen:"Aobei",
				code:"1408"
			},
			{
				name:"大运",
				nameen:"Dayun",
				code:"1409"
			},
			{
				name:"嶂背",
				nameen:"Zhangbei",
				code:"1410"
			},
			{
				name:"南约",
				nameen:"Nanyue",
				code:"1411"
			},
			{
				name:"宝龙",
				nameen:"Baolong",
				code:"1412"
			},
			{
				name:"锦龙",
				nameen:"Jinlong",
				code:"1413"
			},
			{
				name:"坪山围",
				nameen:"Pingshanwei",
				code:"1414"
			},
			{
				name:"坪山广场",
				nameen:"Pingshan Square",
				code:"1415"
			},
			{
				name:"坪山中心",
				nameen:"Pingshan Center",
				code:"1416"
			},
			{
				name:"坑梓",
				nameen:"Kengzi",
				code:"1417"
			},
			{
				name:"沙田",
				nameen:"ShaTian",
				code:"1418"
			},
						
		]
	},{  //16号线
		line:'16',
		zdList:[
			{
				name:"园山西坑",
				nameen:"Yuanshan Xikeng",
				code:"1601"
			},{
				name:"安良",
				nameen:"Anliang",
				code:"1602"
			},{
				name:"福坑",
				nameen:"Fukeng",
				code:"1603"
			},{
				name:"大康",
				nameen:"DaKang",
				code:"1604"
			},{
				name:"园山",
				nameen:"Yuanshan",
				code:"1605"
			},{
				name:"大安",
				nameen:"Da'an",
				code:"1606"
			},{
				name:"吉溪",
				nameen:"Jixi",
				code:"1607"
			},{
				name:"金源",
				nameen:"JinYuan",
				code:"1608"
			},{
				name:"大运",
				nameen:"Universiade",
				code:"1609"
			},
			{
				name:"大运中心",
				nameen:"Universiade Center",
				code:"1610"
			},
			{
				name:"龙城公园",
				nameen:"Longcheng Park",
				code:"1611"
			},
			{
				name:"黄阁坑",
				nameen:"Huanggekeng",
				code:"1612"
			},
			{
				name:"愉园",
				nameen:"Yuyuan",
				code:"1613"
			},
			{
				name:"回龙埔",
				nameen:"Huilongpu",
				code:"1614"
			},
			{
				name:"尚景",
				nameen:"Shangjing",
				code:"1615"
			},
			{
				name:"盛平",
				nameen:"Shengping",
				code:"1616"
			},
			{
				name:"龙园",
				nameen:"Longyuan",
				code:"1617"
			},
			{
				name:"双龙",
				nameen:"Shuanglong",
				code:"1618"
			},
			{
				name:"新塘围",
				nameen:"Xintangwei",
				code:"1619"
			},
			{
				name:"龙东",
				nameen:"Longdong",
				code:"1620"
			},
			{
				name:"宝龙同乐",
				nameen:"Baolongtongle",
				code:"1621"
			},
			{
				name:"坪山",
				nameen:"Pingshan",
				code:"1622"
			},
			{
				name:"新和",
				nameen:"Xinhe",
				code:"1623"
			},
			{
				name:"六和",
				nameen:"Liuhe",
				code:"1624"
			},
			{
				name:"坪山围",
				nameen:"Pingshan wei",
				code:"1625"
			},
			{
				name:"坪环",
				nameen:"Pinghuan",
				code:"1626"
			},
			{
				name:"东纵纪念馆",
				nameen:"Dongjiang Column Memorial",
				code:"1627"
			},
			{
				name:"沙壆",
				nameen:"Shabo",
				code:"1628"
			},
			{
				name:"燕子湖",
				nameen:"Yanzihu",
				code:"1629"
			},
			{
				name:"石井",
				nameen:"Shijing",
				code:"1630"
			},
			{
				name:"技术大学",
				nameen:"Technology University",
				code:"1631"
			},
			{
				name:"田心",
				nameen:"Tianxin",
				code:"1632"
			},					
		]
	}
	
	,{  //20号线
		line:'20',
		zdList:[
			{
				name:"机场北",
				nameen:"Airport North",
				code:"2001"
			},
			{
				name:"国展南",
				nameen:"Shenzhen World South",
				code:"2002"
			},
			{
				name:"国展",
				nameen:"Shenzhen World",
				code:"2003"
			},
			{
				name:"国展北",
				nameen:"Shenzhen World North",
				code:"2004"
			},
			{
				name:"会展城",
				nameen:"Convention & Exhibition City",
				code:"2005"
			},
						
		]
	}
];
