"""
htmledit.py

Python -> Browser DOM controller for Flask.

Usage:

import htmledit

htmledit.text("#status", "Running")
htmledit.js("console.log('hello')")
"""

import __main__
import threading
import json

from flask import jsonify, Response, request


# -------------------------------------------------
# Find Flask app
# -------------------------------------------------

if not hasattr(__main__, "app"):
    raise RuntimeError(
        "htmledit requires your Flask app to be named 'app' in __main__"
    )

app = __main__.app


# -------------------------------------------------
# Internal state
# -------------------------------------------------

_commands = []
_lock = threading.Lock()

_initialized = False


# -------------------------------------------------
# Client runtime
# -------------------------------------------------

CLIENT_JS = r"""
(function(){

if(window.__htmledit_loaded)
    return;

window.__htmledit_loaded = true;


async function htmledit_poll(){

    try{

        let res = await fetch("/__htmledit__/poll");
        let cmds = await res.json();


        for(let cmd of cmds){

            try{

                switch(cmd.type){


                    case "js":
                        eval(cmd.code);
                        break;


                    case "text":

                        let e1=document.querySelector(cmd.selector);

                        if(e1)
                            e1.textContent=cmd.value;

                        break;


                    case "html":

                        let e2=document.querySelector(cmd.selector);

                        if(e2)
                            e2.innerHTML=cmd.value;

                        break;


                    case "hide":

                        let e3=document.querySelector(cmd.selector);

                        if(e3)
                            e3.style.display="none";

                        break;


                    case "show":

                        let e4=document.querySelector(cmd.selector);

                        if(e4)
                            e4.style.display="";

                        break;


                    case "add_class":

                        let e5=document.querySelector(cmd.selector);

                        if(e5)
                            e5.classList.add(cmd.class);

                        break;


                    case "remove_class":

                        let e6=document.querySelector(cmd.selector);

                        if(e6)
                            e6.classList.remove(cmd.class);

                        break;


                }


            }catch(err){

                console.error(
                    "htmledit command failed:",
                    err
                );

            }

        }


    }
    catch(err){

        console.error(
            "htmledit connection error:",
            err
        );

    }


    setTimeout(
        htmledit_poll,
        100
    );

}


htmledit_poll();


})();
"""


# -------------------------------------------------
# Queue system
# -------------------------------------------------

def _send(command):

    with _lock:

        _commands.append(command)



def js(code):

    """
    Execute raw JavaScript.
    """

    _send({
        "type":"js",
        "code":code
    })



def text(selector,value):

    _send({
        "type":"text",
        "selector":selector,
        "value":value
    })



def html(selector,value):

    _send({
        "type":"html",
        "selector":selector,
        "value":value
    })



def hide(selector):

    _send({
        "type":"hide",
        "selector":selector
    })



def show(selector):

    _send({
        "type":"show",
        "selector":selector
    })



def add_class(selector,name):

    _send({
        "type":"add_class",
        "selector":selector,
        "class":name
    })



def remove_class(selector,name):

    _send({
        "type":"remove_class",
        "selector":selector,
        "class":name
    })


# -------------------------------------------------
# Flask routes
# -------------------------------------------------

@app.route("/__htmledit__/poll")
def _poll():

    global _commands

    with _lock:

        data=list(_commands)
        _commands.clear()


    return jsonify(data)



@app.route("/__htmledit__/client.js")
def _client():

    return Response(
        CLIENT_JS,
        mimetype="application/javascript"
    )



# -------------------------------------------------
# HTML injection
# -------------------------------------------------

@app.after_request
def _inject(response):
    try:
        # Only touch genuine HTML documents — not JSON, JS, CSS, images, etc.
        if response.mimetype != "text/html":
            return response

        # Skip streamed/passthrough responses (file downloads, etc.)
        if response.direct_passthrough or response.is_streamed:
            return response

        data = response.get_data(as_text=True)
        marker = '<script src="/__htmledit__/client.js"></script>'

        # STRICT CHECK: Only inject if it's already missing the marker AND has a closing body tag.
        # This prevents accidental injection into JSON strings defaulting to text/html.
        if marker not in data and "</body>" in data:
            data = data.replace("</body>", marker + "\n</body>")
            response.set_data(data)

    except Exception as e:
        print("htmledit injection error:", e)

    return response



print(
    "[htmledit] loaded"
)