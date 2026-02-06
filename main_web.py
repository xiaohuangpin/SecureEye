import webview,json,threading,multiprocessing,os,sys
from pathlib import Path
from agent import MultClient
from export import export_to_word
import subprocess
import multiprocessing
#nuitka --standalone --enable-plugin=anti-bloat --include-package-data=docx --include-data-dir=assets=assets --output-dir=dist --windows-icon-from-ico=logo.ico --windows-disable-console --output-dir=dist main_web.py
#--onefile
#pyinstaller --windowed --name secure --add-data "assets;assets" main_web.py
#pyinstaller --windowed --name secure --add-data "assets;assets" --add-data "model_config.json;." -i logo.ico main_web.py
#nuitka --module agent.py --output-dir=dist --include-package=openai --include-package=pillow --noinclude-default-mode=warning --remove-output
multiprocessing.freeze_support()

def open_file_with_default_app(file_path:str) -> None:
    if not os.path.exists(file_path):
        print(f"错误：文件 {file_path} 不存在")
        return False

    try:
        subprocess.Popen(
            ['start', '', file_path],
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return True
    except Exception as e:
        print(f"打开文件失败：{str(e)}")
        return False


class API:
    def __init__(self):
        self.config_path = Path(__file__).parent / "model_config.json"
        self.config = self._load_config()
        self.window = None

    def set_window(self,winodw):
        self.window = winodw

    def _load_config(self):

        if not self.config_path.exists():
            return None
        
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                #a = json.load(f)
                #print(a)
                #print(a['api_key'])
                return json.load(f)
        except Exception:
            return None


    def get_config_status(self):

        if not self.config:
            return {"valid": False}
    
        required = ["api_key", "base_url", "model"]

        valid = all(
            field in self.config and 
            isinstance(self.config[field], str) and 
            self.config[field].strip()
            for field in required
        )

        return {
            "valid": valid,
            "config": self.config if valid else None
        }
    
    def save_config(self, api_key, base_url, model):

        try:
            config = {
                "api_key": api_key.strip(),
                "base_url": base_url.strip(),
                "model": model.strip()
            }
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
            self.config = config
            return {"success": True, "message": "配置保存成功！"}
        except Exception as e:
            return {"success": False, "message": f"配置保存失败: {str(e)}"}
        
    def select_images(self):

        try:
            # 使用系统原生文件选择器
            file_types = (
                "图片文件 (*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tiff;*.webp)",
                "所有文件 (*.*)"
            )
            paths = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=file_types
            )
            return {"success": True, "paths": list(paths) if paths else []}
        except Exception as e:
            return {"success": False, "message": f"文件选择失败: {str(e)}"}
        
    #该函数异步执行，根本不会停止
    def start_generation(self,img_list):

        if not self.config:
            return {"success": False, "message": "配置无效，请先配置模型参数"}
        
        required = ["api_key", "base_url", "model"]

        if not all(field in self.config for field in required):
            return {"success": False, "message": "配置不完整，请检查配置"}
        
        thread = threading.Thread(
            target=self._run_export_task,
            args=(img_list,),
            daemon=True
        )

        thread.start()

        return {"success": True, "message": "任务已启动"}
    

    def _run_export_task(self,img_list):

        try:
            self.window.evaluate_js("window.taskStarted()")

            example = ["未固定的高空作业平台", "裸露的带电电缆"]
            client = MultClient(
                self.config["api_key"],
                self.config["base_url"],
                self.config["model"],
                example
            )
            data = client.batch_infer(img_list, True)
            #output_path = Path(__file__).parent / "image_table.docx"
            output_path = export_to_word(data)
            #DOCX_FILE_PATH = "image_table.docx"
            """
            file_process = multiprocessing.Process(
                target=open_file_with_default_app,
                args=(output_path,),
                name="DocxOpenProcess"  # 进程命名，方便任务管理器识别
            )
            file_process.start()
            file_process.join()
            """
            open_file_with_default_app(output_path)

        except Exception as e:
            error_msg = f"生成失败: {str(e)}"
            self.window.evaluate_js(f'window.taskCompleted(false, "{error_msg}")')

        finally:
            success_msg:str = "生成成功"
            self.window.evaluate_js(f'window.taskCompleted(false, "{success_msg}")')

def get_resource_path(relative_path:str) -> str:
   
    # Nuitka在--onefile模式下会设置__compiled__属性
    if getattr(sys, 'frozen', False):
        # __file__ 在Nuitka中指向临时目录中的模块路径
        base_path = os.path.dirname(__file__)
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    
    return os.path.join(base_path, relative_path)


def main():
    api = API()
    index_path:str = get_resource_path("assets/index.html")

    window = webview.create_window(
        "Model Configurator",
        #url=str(Path(__file__).parent / "assets" / "index.html"),
        url=index_path,
        js_api=api,
        width=600,
        height=450,
        resizable=False,
        frameless=False,  # 保留窗口边框以便移动和关闭
        background_color="#f5f7fa",
        
    )

    api.set_window(window)

    webview.start(debug=False)

if __name__ == "__main__":
    main()
