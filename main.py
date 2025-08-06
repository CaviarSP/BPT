from pkg.plugin.context import register, handler, BasePlugin, APIHost, EventContext
from pkg.plugin.events import *  # 导入事件类
from pkg.platform.types import MessageChain,Plain,Image
from google import genai
from google.genai import types
import base64
from datetime import datetime
import requests
import re
import yaml


# 注册插件
@register(name="BPT", description="record blood pressure", version="0.1", author="Caviar")
class BPT(BasePlugin):
    gemini_key = ''
    # 插件加载时触发
    def __init__(self, host: APIHost):
        path = '/app/plugins/BPT/config.yaml'
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        self.gemini_key = config.get('gemini_key', '')
        pass

    # 异步初始化
    async def initialize(self):
        pass


    @handler(PersonMessageReceived)
    async def person_normal_message_received(self, ctx: EventContext):
       
        msgc: MessageChain
        msgc = ctx.event.message_chain  # 这里的 event 即为 PersonNormalMessageReceived 的对象

        if msgc.get_first(Plain) == Plain("新建表格"):
            wecomapi = wecomAPI(corpid=self.corpid,appsecret=self.appsecret,docid=self.docid)
            res = wecomapi.create_doc(type_id=10,name="血压记录v1")
            print("血压记录v1--",res.json())

        if msgc.get_first(Image): 
            image_base64=msgc.get_first(Image).base64
            if image_base64.startswith("data:image"):
                base64_str = image_base64.split(",")[1]
            else:
                base64_str = image_base64
            image_data = base64.b64decode(base64_str)
            with open("temp.jpg", "wb") as f:
                f.write(image_data)
        
            client = genai.Client(api_key= self.gemini_key)

            prompt="回复图中血压计的三个读数，数字中间用#分隔。"

            my_file = client.files.upload(file="temp.jpg")

            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[my_file, prompt],
            )
            print(response.text)
            self.form_data(response.text)


            await ctx.reply( [response.text] )


            ctx.prevent_default()

    # 当收到个人消息时触发
    @handler(PersonNormalMessageReceived)
    async def person_normal_message_received(self, ctx: EventContext):
        ctx.prevent_default()

    # 当收到群消息时触发
    @handler(GroupNormalMessageReceived)
    async def group_normal_message_received(self, ctx: EventContext):
        ctx.prevent_default()

    # 插件卸载时触发
    def __del__(self):
        pass


        
    def form_data(self,text):
        pattern = r"\b\d{2,3}#\d{2,3}#\d{2,3}\b"
        match = re.search(pattern,text)
        if match:
            #print('match')
            wecomapi = wecomAPI(corpid=self.corpid,appsecret=self.appsecret,docid=self.docid)
            d1, d2, d3 = match.group().split("#")
            now = datetime.now()
            ym_str = now.strftime(r"%Y-%m")
            #print(ym_str)
            sheet_list = wecomapi.get_sheet().json()["sheet_list"]
            #print(type(sheet_list),sheet_list)
            exist_flag = False
            sheet_id = ''
            for json in sheet_list:
                if json["title"] == ym_str:
                    exist_flag = True
                    sheet_id = json["sheet_id"]
                    break
            #print(sheet_id)
            if exist_flag == False:
                sheet_id = wecomapi.add_sheet(ym_str)
            wecomapi.add_record(sheet_id,int(d1),int(d2),int(d3))
            return [d1, d2, d3]
            

            


class wecomAPI():
    corpid = ""
    appsecret = ""
    access_token = ''
    docid = '' #v1
    def __init__(self):
        path = '/app/plugins/BPT/config.yaml'
        with open(path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        self.corpid = config.get('corpid', '')
        self.appsecret = config.get('appsecret', '')
        self.docid = config.get('docid', '')
        self.access_token = ''
        pass

    def get_access_token(self):
        url = f'https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={self.corpid}&corpsecret={self.appsecret}'
        response = requests.get(url)
        if response.status_code == 200:
            print(response.json())
            access_token = response.json()["access_token"]
            self.access_token = access_token 

        
    def create_doc(self,name:str,type_id:int):#4：表格，10：智能表格
        self.get_access_token()
        post = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/create_doc?access_token={self.access_token}"
        payload = {
            "doc_type": type_id,                     
            "doc_name": name,
            }
        res = requests.post(post,json=payload)
        return res
    
    def get_sheet(self):
        self.get_access_token()
        post = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/get_sheet?access_token={self.access_token}"
        payload = {
            "docid": self.docid,                     
            "need_all_type_sheet":False
            }
        res = requests.post(post,json=payload)
        print(res)
        return res
        

    def add_sheet(self,name:str):
        #self.get_access_token()
        post = f"https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_sheet?access_token={self.access_token}"
        payload = {
            "docid": self.docid,                     
            "properties": {
                "title":name
            }
        }
        res = requests.post(post,json=payload)
        sheet_id = res.json()["properties"]["sheet_id"]
        
        
        self.add_fields_datetime(sheet_id)
        self.add_fields_number(sheet_id,"高压（mmHg）")
        self.add_fields_number(sheet_id,"低压（mmHg）")
        self.add_fields_number(sheet_id,"脉搏（次/分）")

        for field in self.get_fields(sheet_id).json()["fields"]:
            if field["field_title"] == "智能表列":
                field_id= field["field_id"]
                self.remove_fields(sheet_id,field_id)

        return sheet_id
    
    def get_fields(self,sheet_id:str):
        post= f'https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/get_fields?access_token={self.access_token}'
        payload = {
            "docid": self.docid,
            "sheet_id": sheet_id,
            "limit": 5
        }
        return requests.post(post,json=payload)   
        
    
    def remove_fields(self,sheet_id:str,field_id:str):
        post= f'https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/delete_fields?access_token={self.access_token}'
        payload = {
            "docid": self.docid,
            "sheet_id": sheet_id,
            "field_ids": [
                field_id
            ]
        }
        requests.post(post,json=payload)

    def add_fields_datetime(self,sheet_id:str): #typr: FIELD_TYPE_TEXT,FIELD_TYPE_NUMBER,FIELD_TYPE_DATE_TIME  https://developer.work.weixin.qq.com/document/path/99904#fieldtype
        post= f'https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_fields?access_token={self.access_token}'
        payload = {
            "docid": self.docid,
            "sheet_id": sheet_id,
            "fields": [
                {
                    "field_title": "时间",
                    "field_type": "FIELD_TYPE_DATE_TIME",
                    "property_date_time": {
                        "format": "yyyy-mm-dd hh:mm",
                        "auto_fill": True
                    }
                }
            ]
        }
        res=requests.post(post,json=payload)

    def add_fields_number(self,sheet_id:str,title:str): 
        post= f'https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_fields?access_token={self.access_token}'
        payload = {
            "docid": self.docid,
            "sheet_id": sheet_id,
            "fields": [
                {
                    "field_title":title,
                    "field_type": "FIELD_TYPE_NUMBER",
                    "property_number": {
                        "decimal_places": 0  # 设置为0表示仅允许整数
                    }
                }
            ]
        }
        requests.post(post,json=payload)

    def add_record(self,sheet_id,d1,d2,d3):
        post= f'https://qyapi.weixin.qq.com/cgi-bin/wedoc/smartsheet/add_records?access_token={self.access_token}'
        payload = {
            "docid": self.docid,
            "sheet_id": sheet_id,
            "key_type": "CELL_VALUE_KEY_TYPE_FIELD_TITLE",
            "records": [
                {
                    "values": {
                        "高压（mmHg）": d1,
                        "低压（mmHg）": d2,
                        "脉搏（次/分）": d3
                    }
                }
            ]
        }
        requests.post(post,json=payload)
