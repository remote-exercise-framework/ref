from flask import Flask, render_template, Blueprint, redirect, url_for
from app import app

@app.route('/task/<int:task_id>/status')
def task_status(task_id):
    return render_template('index.html')

@app.route('/task/<int:task_id>/stop')
def task_stop(task_id):
    return render_template('index.html')

@app.route('/task/<int:task_id>/output')
def task_output(task_id):
    return render_template('index.html')

