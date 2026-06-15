import dis
import marshal
import sys

def decompile_pyc(pyc_path, out_txt_path):
    with open(pyc_path, 'rb') as f:
        f.read(16)
        try:
            code_obj = marshal.load(f)
            with open(out_txt_path, 'w') as out:
                sys.stdout = out
                dis.dis(code_obj)
                sys.stdout = sys.__stdout__
            print("Successfully decompiled " + pyc_path + " to " + out_txt_path)
        except Exception as e:
            sys.stdout = sys.__stdout__
            print("Failed to decompile " + pyc_path + ": " + str(e))

decompile_pyc("/Users/haiannguyen/Desktop/Day-13-Lab-Observathon/observathon-sim2_extracted/PYZ.pyz_extracted/observathon_sim/_faults.pyc", "dis_faults.txt")
