#!/usr/bin/env python3
# coding: utf-8
# File: MedicalGraph.py
# Author: lhy<lhy_in_blcu@126.com,https://huangyong.github.io>
# Date: 18-10-3

import argparse
import json
import os
import time
from collections import Counter
from dataclasses import dataclass

from graph_connection import connect_graph

BATCH_SIZE = 2000
NODE_LABELS = ('Disease', 'Symptom', 'Drug', 'Food', 'Check', 'Department', 'Producer')


@dataclass(frozen=True)
class RelationshipSpec:
    start: str
    end: str
    rel_type: str
    rel_name: str
    pairs: set[tuple[str, str]]


class MedicalGraph:
    def __init__(self):
        cur_dir = '/'.join(os.path.abspath(__file__).split('/')[:-1])
        self.data_path = os.path.join(cur_dir, 'data/medical.json')
        self.g = connect_graph()

    '''读取文件，返回节点行和关系定义'''
    def read_nodes(self):
        drugs = set()  # 药品
        foods = set()  # 食物
        checks = set()  # 检查
        departments = set()  # 科室
        producers = set()  # 药品大类
        symptoms = set()  # 症状
        disease_infos = []  # 疾病信息

        # 构建节点实体关系
        rels_department = set()  # 科室－科室关系
        rels_noteat = set()  # 疾病－忌吃食物关系
        rels_doeat = set()  # 疾病－宜吃食物关系
        rels_recommandeat = set()  # 疾病－推荐吃食物关系
        rels_commonddrug = set()  # 疾病－通用药品关系
        rels_recommanddrug = set()  # 疾病－热门药品关系
        rels_check = set()  # 疾病－检查关系
        rels_drug_producer = set()  # 厂商－药物关系
        rels_symptom = set()  # 疾病症状关系
        rels_acompany = set()  # 疾病并发关系
        rels_category = set()  # 疾病与科室之间的关系

        with open(self.data_path, encoding='utf-8') as f:
            for line in f:
                data_json = json.loads(line)
                disease = data_json['name']
                disease_dict = {
                    'name': disease,
                    'desc': '',
                    'prevent': '',
                    'cause': '',
                    'easy_get': '',
                    'cure_department': '',
                    'cure_way': '',
                    'cure_lasttime': '',
                    'cured_prob': '',
                }

                for symptom in data_json.get('symptom', []):
                    symptoms.add(symptom)
                    rels_symptom.add((disease, symptom))

                for acompany in data_json.get('acompany', []):
                    rels_acompany.add((disease, acompany))

                for key in ('desc', 'prevent', 'cause', 'easy_get',
                            'cure_way', 'cure_lasttime', 'cured_prob'):
                    if key in data_json:
                        disease_dict[key] = data_json[key]

                if 'cure_department' in data_json:
                    cure_department = data_json['cure_department']
                    departments.update(cure_department)
                    if len(cure_department) == 1:
                        rels_category.add((disease, cure_department[0]))
                    if len(cure_department) == 2:
                        rels_department.add((cure_department[1], cure_department[0]))
                        rels_category.add((disease, cure_department[1]))
                    disease_dict['cure_department'] = cure_department

                for drug in data_json.get('common_drug', []):
                    drugs.add(drug)
                    rels_commonddrug.add((disease, drug))

                for drug in data_json.get('recommand_drug', []):
                    drugs.add(drug)
                    rels_recommanddrug.add((disease, drug))

                for food in data_json.get('not_eat', []):
                    foods.add(food)
                    rels_noteat.add((disease, food))

                for food in data_json.get('do_eat', []):
                    foods.add(food)
                    rels_doeat.add((disease, food))

                for food in data_json.get('recommand_eat', []):
                    foods.add(food)
                    rels_recommandeat.add((disease, food))

                for check in data_json.get('check', []):
                    checks.add(check)
                    rels_check.add((disease, check))

                for detail in data_json.get('drug_detail', []):
                    producer = detail.split('(')[0]
                    drug = detail.split('(')[-1].replace(')', '')
                    producers.add(producer)
                    rels_drug_producer.add((producer, drug))

                disease_infos.append(disease_dict)

        nodes = {
            'Disease': disease_infos,
            'Drug': [{'name': name} for name in drugs],
            'Food': [{'name': name} for name in foods],
            'Check': [{'name': name} for name in checks],
            'Department': [{'name': name} for name in departments],
            'Producer': [{'name': name} for name in producers],
            'Symptom': [{'name': name} for name in symptoms],
        }
        relationships = [
            RelationshipSpec('Disease', 'Food', 'recommand_eat', '推荐食谱', rels_recommandeat),
            RelationshipSpec('Disease', 'Food', 'no_eat', '忌吃', rels_noteat),
            RelationshipSpec('Disease', 'Food', 'do_eat', '宜吃', rels_doeat),
            RelationshipSpec('Department', 'Department', 'belongs_to', '属于', rels_department),
            RelationshipSpec('Disease', 'Drug', 'common_drug', '常用药品', rels_commonddrug),
            RelationshipSpec('Producer', 'Drug', 'drugs_of', '生产药品', rels_drug_producer),
            RelationshipSpec('Disease', 'Drug', 'recommand_drug', '好评药品', rels_recommanddrug),
            RelationshipSpec('Disease', 'Check', 'need_check', '诊断检查', rels_check),
            RelationshipSpec('Disease', 'Symptom', 'has_symptom', '症状', rels_symptom),
            RelationshipSpec('Disease', 'Disease', 'acompany_with', '并发症', rels_acompany),
            RelationshipSpec('Disease', 'Department', 'belongs_to', '所属科室', rels_category),
        ]
        return nodes, relationships

    '''建立唯一约束，同时为 name 建索引'''
    def create_constraints(self):
        for label in NODE_LABELS:
            self.g.run(
                f'CREATE CONSTRAINT {label.lower()}_name_unique IF NOT EXISTS '
                f'FOR (n:{label}) REQUIRE n.name IS UNIQUE'
            ).data()

    '''清空当前数据库，仅用于专用实例'''
    def reset(self):
        self.g.run('MATCH (n) DETACH DELETE n').data()

    '''批量 upsert 节点'''
    def merge_nodes(self, label, rows):
        query = (
            f'UNWIND $rows AS row '
            f'MERGE (n:{label} {{name: row.name}}) '
            f'SET n += row'
        )
        for start in range(0, len(rows), BATCH_SIZE):
            self.g.run(query, rows=rows[start:start + BATCH_SIZE]).data()

    '''批量 upsert 关系'''
    def merge_relationships(self, spec):
        query = (
            f'UNWIND $rows AS row '
            f'MATCH (p:{spec.start} {{name: row.p}}) '
            f'MATCH (q:{spec.end} {{name: row.q}}) '
            f'MERGE (p)-[r:{spec.rel_type}]->(q) '
            f'ON CREATE SET r.name = $rel_name'
        )
        rows = [{'p': p, 'q': q} for p, q in spec.pairs]
        for start in range(0, len(rows), BATCH_SIZE):
            self.g.run(
                query, rows=rows[start:start + BATCH_SIZE], rel_name=spec.rel_name
            ).data()

    '''校验导入结果，避免缺边或重复数据被静默接受'''
    def verify(self, nodes, relationships):
        expected_nodes = {
            label: len({row['name'] for row in rows}) for label, rows in nodes.items()
        }
        expected_rels = {}
        for spec in relationships:
            expected_rels[spec.rel_type] = expected_rels.get(spec.rel_type, 0) + len(spec.pairs)

        actual_nodes = {
            row['label']: row['c']
            for row in self.g.run(
                'MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c'
            ).data()
            if row['label'] in NODE_LABELS
        }
        actual_rels = {
            row['type']: row['c']
            for row in self.g.run(
                'MATCH ()-[r]->() RETURN type(r) AS type, count(*) AS c'
            ).data()
            if row['type'] in expected_rels
        }

        problems = []
        for label, expected in expected_nodes.items():
            actual = actual_nodes.get(label, 0)
            if actual != expected:
                problems.append(f'{label}: 期望 {expected}，实际 {actual}')
        for rel_type, expected in expected_rels.items():
            actual = actual_rels.get(rel_type, 0)
            if actual != expected:
                problems.append(f'{rel_type}: 期望 {expected}，实际 {actual}')
        if problems:
            raise SystemExit('导入校验失败：\n' + '\n'.join(problems))

    '''导入图谱'''
    def import_graph(self, reset=False):
        started = time.perf_counter()
        if reset:
            print('清空数据库...')
            self.reset()
        print('创建约束...')
        self.create_constraints()

        print('读取数据...')
        nodes, relationships = self.read_nodes()
        duplicates = sorted(
            name
            for name, count in Counter(row['name'] for row in nodes['Disease']).items()
            if count > 1
        )
        if duplicates:
            print(f'警告：源数据有重复疾病名，已合并为同一节点：{"、".join(duplicates)}')

        print('导入节点...')
        for label, rows in nodes.items():
            self.merge_nodes(label, rows)

        print('导入关系...')
        for spec in relationships:
            self.merge_relationships(spec)

        print('校验...')
        self.verify(nodes, relationships)

        node_total = sum(len({row['name'] for row in rows}) for rows in nodes.values())
        rel_total = sum(len(spec.pairs) for spec in relationships)
        elapsed = time.perf_counter() - started
        print(f'完成：{node_total:,} 个节点，{rel_total:,} 条关系，用时 {elapsed:.1f}s')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='将 data/medical.json 导入 Neo4j。')
    parser.add_argument(
        '--reset', action='store_true',
        help='导入前清空当前数据库；仅用于专用实例',
    )
    args = parser.parse_args()
    MedicalGraph().import_graph(reset=args.reset)
