#pragma once
#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <filesystem>
#include <cctype>

inline std::string trim(const std::string &s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
}

inline std::vector<std::vector<int>> read_file(const std::string &path) {
    namespace fs = std::filesystem;
    std::vector<std::vector<int>> empty;

    if (!fs::exists(path) || !fs::is_regular_file(path))
        return empty;

    std::ifstream fin(path);
    if (!fin.is_open())
        return empty;

    std::vector<std::vector<int>> upperTriangle;
    std::string line;

    while (std::getline(fin, line)) {
        std::string stripped = trim(line);
        if (stripped.empty() || stripped[0] == '#')
            continue; 

        std::vector<int> row;
        std::stringstream ss(stripped);
        std::string token;

        while (ss >> token) {
            std::string val = trim(token);
            if (!val.empty()) {
                for (char c : val)
                    if (!std::isdigit(c) && c != '-' && c != '+')
                        return empty;
                row.push_back(std::stoi(val));
            }
        }

        if (!row.empty())
            upperTriangle.push_back(row);
    }

    if (upperTriangle.empty())
        return empty;

    size_t n = upperTriangle.size() + 1; 
    std::vector<std::vector<int>> matrix(n, std::vector<int>(n, -1));

    for (size_t i = 0; i < upperTriangle.size(); ++i) {
        for (size_t j = 0; j < upperTriangle[i].size(); ++j) {
            size_t col = i + j + 1;
            if (col >= n)
                return empty;
            matrix[i][col] = upperTriangle[i][j];
            matrix[col][i] = upperTriangle[i][j]; 
        }
        matrix[i][i] = 0;
    }

    matrix[n - 1][n - 1] = 0;
    return matrix;
}
