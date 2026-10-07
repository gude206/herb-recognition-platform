import type { Herb } from '../types/herb'
import honeysuckle from '../assets/images/honeysuckle-generated.jpg'
import astragalus from '../assets/images/astragalus-generated.jpg'
import licorice from '../assets/images/licorice-generated.jpg'
import danshen from '../assets/images/danshen-generated.jpg'
import chrysanthemum from '../assets/images/chrysanthemum-generated.jpg'
import forsythia from '../assets/images/forsythia-generated.jpg'
import angelica from '../assets/images/angelica-generated.jpg'
import mint from '../assets/images/mint-generated.jpg'

const base = (id: string, name: string, latinName: string, image: string, property: string, effects: string[], part: string, aliases: string | string[], family: string, flavor: string[], meridians: string[], description: string, morphology: string): Herb => ({
  id, name, latinName, image, property, effects, medicinalPart: [part], aliases: Array.isArray(aliases) ? aliases : aliases.split('、'), family, flavor, meridians, description, morphology,
  traditionalUses: [`${effects[0]}，为传统本草知识条目中常见记载`, '作为植物识别与本草学习的参考内容'],
  precautions: ['本条目用于植物识别与知识科普，具体应用请查阅专业资料并咨询专业人士。'],
  background: `${name}是本草文化中常见的植物条目。平台结合植物形态、传统知识与数字化资料，为学习者提供清晰、可检索的介绍。`,
})

export const mockHerbs: Herb[] = [
  base('h001','金银花','Lonicera japonica Thunb.',honeysuckle,'寒',['清热解毒','疏散风热'],'花','忍冬花、双花','忍冬科',['甘','寒'],['肺','心','胃'],'藤本植物，花初开白色，后转为黄色，常见于庭园与山野。','多年生半常绿缠绕藤本，叶对生，花成对腋生。'),
  base('h002','黄芪','Astragalus membranaceus (Fisch.) Bge.',astragalus,'微温',['补气养血','补气固表','利水消肿'],'根','黄耆、绵芪','豆科',['甘','微温'],['肺','脾'],'豆科多年生草本，根部是传统本草资料中常见的药用部位。','茎直立或稍倾斜，奇数羽状复叶，小叶椭圆形。'),
  base('h003','甘草','Glycyrrhiza uralensis Fisch.',licorice,'平',['止咳平喘','调和诸药','润肺止咳'],'根','甜草、国老','豆科',['甘','平'],['心','肺','脾','胃'],'豆科多年生草本，羽状复叶，花序紫色，常见于北方草原地区。','直立草本，叶面有腺点，荚果弯曲呈镰刀状。'),
  base('h004','丹参','Salvia miltiorrhiza Bunge',danshen,'微寒',['活血化瘀','通经止痛'],'根','赤参、紫丹参','唇形科',['苦','微寒'],['心','肝'],'唇形科多年生草本，紫色花序醒目，根部呈红色。','茎四棱形，叶对生，轮伞花序顶生。'),
  base('h005','菊花','Chrysanthemum morifolium Ramat.',chrysanthemum,'微寒',['清热解毒','平肝明目'],'花','甘菊、秋菊','菊科',['甘','苦','微寒'],['肺','肝'],'菊科多年生草本，头状花序形态丰富，是常见的观赏与文化植物。','叶互生，羽状浅裂，头状花序顶生。'),
  base('h006','连翘','Forsythia suspensa (Thunb.) Vahl',forsythia,'微寒',['清热解毒','消肿散结'],'果实','黄花杆、青翘','木犀科',['苦','微寒'],['肺','心','小肠'],'早春先叶开花，金黄色花朵是识别连翘的重要特征。','落叶灌木，枝条中空，花冠四裂。'),
  base('h007','当归','Angelica sinensis (Oliv.) Diels',angelica,'温',['补气养血','补血活血','调经止痛'],'根','秦归、云归','伞形科',['甘','辛','温'],['肝','心','脾'],'伞形科多年生草本，花序呈复伞形，具有浓郁芳香。','茎紫绿色，叶片二至三回羽状分裂。'),
  base('h008','薄荷','Mentha canadensis L.',mint,'凉',['疏散风热','清利头目'],'叶','银丹草、夜息香','唇形科',['辛','凉'],['肺','肝'],'唇形科芳香草本，叶片具清新气味，常见于庭园种植。','茎四棱形，叶对生，轮伞花序腋生。'),
  base('h009','枸杞','Lycium barbarum L.',astragalus,'平',['滋补肝肾','益精明目'],'果实','枸杞子、红耳坠','茄科',['甘','平'],['肝','肾'],'枝条细长，果实成熟后呈鲜红色，是常见的园艺与本草植物。','灌木，叶互生或簇生，花淡紫色。'),
  base('h010','人参','Panax ginseng C. A. Mey.',angelica,'微温',['大补元气','复脉固脱'],'根','园参、棒槌','五加科',['甘','微苦','微温'],['脾','肺','心','肾'],'五加科多年生草本，掌状复叶轮生，果实成熟时呈红色。','茎单生，掌状复叶，伞形花序顶生。'),
  base('h011','板蓝根','Isatis indigotica Fortune',mint,'寒',['清热解毒','凉血利咽'],'根','蓝根、大青根','十字花科',['苦','寒'],['心','胃'],'十字花科草本，基生叶较大，果实扁平，是北方常见植物。','茎直立，上部多分枝，总状花序顶生。'),
  base('h012','蒲公英','Taraxacum mongolicum Hand.-Mazz.',chrysanthemum,'寒',['清热解毒','消肿散结'],'全草','黄花地丁、婆婆丁','菊科',['苦','甘','寒'],['肝','胃'],'菊科多年生草本，黄色头状花序，种子带有白色冠毛。','基生叶莲座状排列，瘦果具白色冠毛。'),
  base('h013','黄芩','Scutellaria baicalensis Georgi',forsythia,'寒',['清热燥湿','泻火解毒'],'根','山茶根、土金茶根','唇形科',['苦','寒'],['肺','胆','脾'],'唇形科多年生草本，花蓝紫色，根外皮黄褐色。','茎直立，叶片披针形，花冠二唇形。'),
  base('h014','麦冬','Ophiopogon japonicus (Thunb.) Ker Gawl.',mint,'微寒',['养阴生津','润肺清心'],'块根','麦门冬、沿阶草','天门冬科',['甘','微苦','微寒'],['心','肺','胃'],'多年生常绿草本，叶丛生，常作为林下地被植物。','叶细长线形，花葶短，浆果蓝黑色。'),
  base('h015','桔梗','Platycodon grandiflorus (Jacq.) A. DC.',honeysuckle,'平',['宣肺利咽','祛痰排脓'],'根','包袱花、铃铛花','桔梗科',['苦','辛','平'],['肺'],'桔梗科多年生草本，花蕾膨大似气球，蓝紫色花朵呈钟形。','茎直立，叶互生，花冠宽钟形。'),
  base('h016','白芍','Paeonia lactiflora Pall.',chrysanthemum,'微寒',['养血调经','平肝止痛'],'根','白花芍药','芍药科',['苦','酸','微寒'],['肝','脾'],'芍药科多年生草本，花大而美丽，具有较高观赏价值。','茎丛生，二回三出复叶，花单生枝顶。'),
]

export const effectOptions = ['清热解毒','补气养血','活血化瘀','止咳平喘','滋补肝肾']
export const propertyOptions = ['寒','热','温','凉','平']
export const partOptions = ['根','茎','叶','花','果实','种子']


